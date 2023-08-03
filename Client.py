from concurrent import futures

import threading

import sys
import grpc
import chat_pb2
import chat_pb2_grpc

from tkinter import *

# The next few lines create the UI, adding 2 buttons for logging out and submitting a message.
rootWindow = Tk()
rootWindow.title("UWO Chat")

rootWindow.rowconfigure(0, minsize=600, weight=1)
rootWindow.columnconfigure(1, minsize=600, weight=1)

leftFrame = Frame(master=rootWindow, relief=RAISED, bd=5)

listOfConnections = Label(master=leftFrame, text="List of Connections:\r\n", font=("Arial", 12))
logoutButton = Button(master=leftFrame, text="Logout", font=("Arial", 12))
message = Text(master=leftFrame, width=20, height=20, wrap=WORD, font=("Arial", 12))
message.insert("1.0", "Insert your message here")
submitButton = Button(master=leftFrame, text="Submit", font=("Arial", 12))
msgHistory = Text(master=rootWindow, font=("Arial", 12))
msgHistory.insert(END, "Chat History: \r\n")
msgHistory.config(state=DISABLED) # Make the message history (Right panel) read only.

listOfConnections.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
logoutButton.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
message.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
submitButton.grid(row=3, column=0, sticky="ew", padx=10, pady=10)

msgHistory.grid(row=0, column=1, sticky="nsew")
leftFrame.grid(row=0, column=0, sticky="ns")


# This class is responsible for handling any incoming requests.
class ChatService():
    
    def sendMessage(self, request, context):
        print("Received a message: " + request.messageContent + "\r\n")
        origin = request.client # Where the message came from (which client); a name or IP address.
        msgContent = request.messageContent # What the message says
        insertedText = origin + ": " + msgContent + "\r\n" #Concatenate them
        msgHistory.config(state=NORMAL)
        msgHistory.insert(END, insertedText)
        msgHistory.config(state=DISABLED)
        return chat_pb2.sendMessageStatus(status="Successful")

    def login(self, request, context):
        print("A user logged in\r\n")
        connections = listOfConnections['text'] # listOfConnection.cget("text") would also work
        connections = connections + "\r\n" + request.name
        listOfConnections.config(text=connections)
        return chat_pb2.loginStatus(response="Successful", clientList=connections)

    def logout(self, request, context):
        print("A user logged out\r\n")
        connections = listOfConnections['text'] # listOfConnection.cget("text") would also work
        userList = connections.split("\r\n")
        userList.remove(request.name)
        connections = "\r\n".join(userList)
        listOfConnections.config(text=connections)
        return chat_pb2.logoutStatus(status="Successful")


    def addServer(self, request, context):
        print()

    def getUsers(self, request, context):
        print()

    def getMessages(self, request, context):
        print()

    def getKnownServers(self, request, context):
        print()


def server():
    # Creates a server with 24 max worker threads.
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=24))
    # Add ChatServicer to the server (so we can call the RPC)
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatService(), server)
    # Add a port to service the server
    address = sys.argv[4] + ":" + sys.argv[2] #Arg 4 is hostname for client (can be "localhost")
    server.add_insecure_port(address)

    print("Starting gRPC Server")
    server.start()
    server.wait_for_termination()


# Get the user's selected name from the command line
userName = sys.argv[1]

# Variable to hold number of messages sent by this client so far.
seqNumber = 1

# Starts a server thread to allow for message processing
serverThread = threading.Thread(target=server, args=(), daemon=True)
serverThread.start()

# Function used to initialize the login when the user first launches the program.
def initialLogin():
    localHostAddress = sys.argv[5] + ":" + sys.argv[3] # Primary server's IP address. argv[5] is primary server hostname (can be localhost)
    with grpc.insecure_channel(localHostAddress) as channel:
        localAddress = sys.argv[4] + ":" + sys.argv[2] # This client's IP address. argv[4] is client hostname (can be localhost)
        stub = chat_pb2_grpc.ChatServiceStub(channel)
        loginResponse = stub.login(chat_pb2.loginRequest(name = userName, address = localAddress))
        if (loginResponse.response == "successful"):
            listOfConnections.config(text=loginResponse.clientList)
        else:
            print(loginResponse.response)
            sys.exit()

# Function to handle the submit button (sends the message to the primary server).
def sendMessageToServer():
    msg = message.get('1.0', END)
    message.delete('1.0', END)
    localHostAddress = sys.argv[5] + ":" + sys.argv[3] # Primary server's IP address.
    with grpc.insecure_channel(localHostAddress) as channel:
        global seqNumber
        stub = chat_pb2_grpc.ChatServiceStub(channel)
        stub.sendMessage(chat_pb2.messagePackage(messageContent = msg, client = userName, sequenceNumber = str(seqNumber)))
        seqNumber = seqNumber + 1

# Function to handle the logout button (sends a signal to the primary server) then terminates.
def logout():
    localHostAddress = sys.argv[5] + ":" + sys.argv[3] # Primary server's IP address.
    with grpc.insecure_channel(localHostAddress) as channel:
        localAddress = sys.argv[4] + ":" + sys.argv[2] # This client's IP address.
        stub = chat_pb2_grpc.ChatServiceStub(channel)
        stub.logout(chat_pb2.logoutRequest(name = userName, address = localAddress))
        sys.exit()


submitButton.config(command=sendMessageToServer)
logoutButton.config(command=logout)

initialLogin()

rootWindow.mainloop()