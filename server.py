from concurrent import futures
from threading import Semaphore, Thread

import sys
import grpc
import chat_pb2 as chat
import chat_pb2_grpc as chat_grpc

SUCCESS_STATUS = "successful"
FAILURE_STATUS = "unsuccessful"
FAILED_LOGIN = "Username already taken"
LOGIN_TYPE = "LI"
LOGOUT_TYPE = "LO"
SEND_MESSAGE_TYPE = "SM"
ADD_SERVER_TYPE = "AS"
TIMEOUT = 3.0


class PrimaryChatService(chat_grpc.ChatServiceServicer):
    users = {}
    message_store = []
    known_servers = {}
    id = None
    server_address = None
    primary_id = None
    primary_address = None
    sequence_number = 1
    message_semaphore = Semaphore(1)
    login_semaphore = Semaphore(1)

    def __init__(self, id, serverAddress, primaryId, primaryAddress):
        self.id = id
        self.server_address = serverAddress
        self.primary_id = primaryId
        self.primary_address = primaryAddress

        if id != primaryId:
            # Notify primary of existence
            with grpc.insecure_channel(primaryAddress) as channel:
                # Create stub
                stub = chat_grpc.ChatServiceStub(channel)
                response = stub.addServer(chat.addServerRequest(id=self.id, address=self.server_address))
                # Get current data and users from primary
                users_response = stub.getUsers(chat.Empty())
                for user in users_response.users:
                    self.users.update({user.name: user.address})

                messages_response = stub.getMessages(chat.Empty())
                self.message_store = messages_response.messages

                # Get known servers (need new grpc for this)
                servers_response = stub.getKnownServers(chat.Empty())
                for server in servers_response.servers:
                    self.known_servers.update({server.id: server.address})

    @staticmethod
    def requestHelperThread(destination, request, type):
        with grpc.insecure_channel(destination) as channel:
            # Create stub
            stub = chat_grpc.ChatServiceStub(channel)
            # Send stub request of proper type
            if type == LOGIN_TYPE:
                response = stub.login(request)
            elif type == LOGOUT_TYPE:
                response = stub.logout(request)
            elif type == SEND_MESSAGE_TYPE:
                response = stub.sendMessage(request)
            elif type == ADD_SERVER_TYPE:
                response = stub.addServer(request)

    def login(self, loginRequest, context) -> chat.loginStatus:
        self.login_semaphore.acquire()
        user = self.users.get(loginRequest.name)
        response = FAILED_LOGIN
        userList = ""
        if user is None:
            self.users.update({loginRequest.name: loginRequest.address})
            if self.id == self.primary_id:
                # Update on backups
                threads = []
                for server in self.known_servers.values():
                    if server != self.server_address:
                        threads.append(Thread(target=PrimaryChatService.requestHelperThread,
                                              args=(server, loginRequest, LOGIN_TYPE)))
                for thread in threads:
                    thread.start()

                for thread in threads:
                    # Can have a timeout on join or wait until all stop. May want to have isAlive()
                    # after to see if thread timed out or not
                    thread.join(timeout=TIMEOUT)
                threads.clear()

                for client in self.users.values():
                    if client != loginRequest.address:
                        threads.append(Thread(target=PrimaryChatService.requestHelperThread,
                                              args=(client, loginRequest, LOGIN_TYPE)))
                for thread in threads:
                    thread.start()

                for thread in threads:
                    # Can have a timeout on join or wait until all stop. May want to have isAlive()
                    # after to see if thread timed out or not
                    thread.join(timeout=TIMEOUT)
                threads.clear()

            response = SUCCESS_STATUS
            userList = "\r\n".join(self.users.keys())

        self.login_semaphore.release()
        return chat.loginStatus(response=response, clientList=userList)

    def logout(self, logoutRequest, context) -> chat.logoutStatus:
        user = self.users.get(logoutRequest.name)
        if user is not None:
            self.users.pop(logoutRequest.name)
            if self.id == self.primary_id:
                # Update on backups
                threads = []
                for server in self.known_servers.values():
                    if server != self.server_address:
                        threads.append(Thread(target=PrimaryChatService.requestHelperThread,
                                              args=(server, logoutRequest, LOGOUT_TYPE)))
                for thread in threads:
                    thread.start()

                for thread in threads:
                    # Can have a timeout on join or wait until all stop. May want to have isAlive()
                    # after to see if thread timed out or not
                    thread.join(timeout=TIMEOUT)
                threads.clear()
                # Send logout to all remaining clients (logged out one removed from list)
                for client in self.users.values():
                    threads.append(Thread(target=PrimaryChatService.requestHelperThread,
                                              args=(client, logoutRequest, LOGOUT_TYPE)))
                for thread in threads:
                    thread.start()

                for thread in threads:
                    # Can have a timeout on join or wait until all stop. May want to have isAlive()
                    # after to see if thread timed out or not
                    thread.join(timeout=TIMEOUT)
                threads.clear()

            return chat.logoutStatus(status=SUCCESS_STATUS)
        else:
            return chat.logoutStatus(status=FAILURE_STATUS)

    def sendMessage(self, messagePackage, context) -> chat.sendMessageStatus:
        self.message_semaphore.acquire()
        self.sequence_number += 1
        if messagePackage.sequenceNumber != self.sequence_number and self.id != self.primary_id:
            # Server is out of sequence try to update
            with grpc.insecure_channel(self.primary_address) as channel:
                # Create stub
                stub = chat_grpc.ChatServiceStub(channel)
                response = stub.getMessages(chat.Empty())
                for message in response.messages:
                    self.message_store.append(message)
                self.sequence_number = len(self.message_store)

        else:
            # Commit Message
            self.message_store.append(messagePackage)
            if self.id == self.primary_id:
                # Send message to all backups
                threads = []
                for server in self.known_servers.values():
                    if server != self.server_address:
                        threads.append(Thread(target=PrimaryChatService.requestHelperThread,
                                              args=(server, messagePackage, SEND_MESSAGE_TYPE)))

                for thread in threads:
                    thread.start()

                for thread in threads:
                    # Can have a timeout on join or wait until all stop. May want to have isAlive()
                    # after to see if thread timed out or not
                    thread.join(timeout=TIMEOUT)
                threads.clear()

                # Send message to all users
                for user in self.users.values():
                    threads.append(Thread(target=PrimaryChatService.requestHelperThread,
                                                  args=(user, messagePackage, SEND_MESSAGE_TYPE)))

                for thread in threads:
                    thread.start()

                for thread in threads:
                    # Can have a timeout on join or wait until all stop. May want to have isAlive()
                    # after to see if thread timed out or not
                    thread.join(timeout=TIMEOUT)
                threads.clear()

        self.message_semaphore.release()
        return chat.sendMessageStatus(status=SUCCESS_STATUS)

    def addServer(self, addServerRequest, context) -> chat.addServerResponse:
        self.known_servers.update({addServerRequest.id: addServerRequest.address})
        # If primary send this new server to all backups
        if self.id == self.primary_id:
            threads = []
            for server in self.known_servers.values():
                if server != self.server_address and server != addServerRequest.address:
                    threads.append(Thread(target=PrimaryChatService.requestHelperThread,
                                          args=(server, addServerRequest, ADD_SERVER_TYPE)))
            for thread in threads:
                thread.start()

            for thread in threads:
                # Can have a timeout on join or wait until all stop. May want to have isAlive()
                # after to see if thread timed out or not
                thread.join(timeout=TIMEOUT)
            threads.clear()

        return chat.addServerResponse(status=SUCCESS_STATUS)

    def getUsers(self, request, context) -> chat.getUsersResponse:
        users = []
        for key, value in self.users.items():
            users.append(chat.loginRequest(name=key, address=value))
        return chat.getUsersResponse(users=users)

    def getMessages(self, request, context) -> chat.getMessagesResponse:
        return chat.getMessagesResponse(messages=self.message_store)

    def getKnownServers(self, request, context) -> chat.getKnownServersResponse:
        servers = []
        for key, value in self.known_servers.items():
            servers.append(chat.Server(id=key, address=value))
        return chat.getKnownServersResponse(servers=servers)

    # Maybe add a bully election algorithm for failure and some sort of heartbeat monitor on primary?

def startServer(port_number, hostname, id, serverAddress, primaryId, primaryAddress, threads):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=threads))
    chat_grpc.add_ChatServiceServicer_to_server(PrimaryChatService(id, serverAddress, primaryId, primaryAddress), server)
    # Server on port number localhost
    server.add_insecure_port(hostname + ':' + port_number)
    server.start()
    server.wait_for_termination()

# Start port#, hostname, id, primary ID, primaryAddress, threads
startServer(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[2] + ':' + sys.argv[1], sys.argv[4], sys.argv[5], int(sys.argv[6]))
