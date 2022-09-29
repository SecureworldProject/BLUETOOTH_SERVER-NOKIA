import time
from bluetooth import *
import threading
import os
#import multiprocessing
#import select



### GLOBAL VARIABLES ###
server_sock = None
client_sock = None
server_thread = None
is_server_running = False



### CONSTANTS ###
# Receiivng data format
SIZE_OF_NAME_LENGTH = 1             # 1 Bytes for the length of the filename(and extension) in bytes (min: 1, max: 256)
MAX_CHUNK_DATA_SIZE = 16*1024       # 16 KiB. The maximum size of each chunk that will be read from the socket
MAX_FILENAME_LENGTH_ALLOWED = 150   # 150 Bytes for the name and its extension (was not set to 255)

UUID = "94f39d29-7d6d-437d-973b-fba39e49d4ee"

# Receiving phases (state machine)
PHASE_GETTING_NAME_LENGTH   = "PHASE_GETTING_NAME_LENGTH"
PHASE_GETTING_NAME          = "PHASE_GETTING_NAME"
PHASE_GETTING_DATA          = "PHASE_GETTING_DATA"

# Paths
FIXED_FILENAME = "capture"
FOLDER_PATH = os.getenv('SECUREMIRROR_CAPTURES')    # Get from environment variable





### CLASSES AND FUNCTIONS ###

# Class that extends Thread and allows to be stoppable from the main thread. Main thread can be used to process user actions/signals like Ctrl+C.
class StoppableThread(threading.Thread):
    def __init__(self,  *args, **kwargs):
        super(StoppableThread, self).__init__(*args, **kwargs)


    def close_server_socket(self):
        global server_sock
        server_sock.close()
        server_sock = None

    def close_client_socket(self):
        global client_sock
        client_sock.close()
        client_sock = None

    def stop(self, force_exit=True):
        print("Stopping server")

        if server_sock:
            self.close_server_socket()
        if client_sock:
            self.close_client_socket()
        is_server_running = False

        if force_exit:
            exit(0)



def main():
    os.system("cls")
    print()
    print("  ____  _            _              _   _        _____                          ")
    print(" |  _ \| |          | |            | | | |      / ____|                         ")
    print(" | |_) | |_   _  ___| |_ ___   ___ | |_| |__   | (___   ___ _ ____   _____ _ __ ")
    print(" |  _ <| | | | |/ _ \ __/ _ \ / _ \| __| '_ \   \___ \ / _ \ '__\ \ / / _ \ '__|")
    print(" | |_) | | |_| |  __/ || (_) | (_) | |_| | | |  ____) |  __/ |   \ V /  __/ |   ")
    print(" |____/|_|\__,_|\___|\__\___/ \___/ \__|_| |_| |_____/ \___|_|    \_/ \___|_|   ")
    print()


    # Use global vars (and allow modifications)
    global server_sock
    global client_sock
    global server_thread

    # Open Bluetooth socket
    server_socket_bound = True
    server_sock = BluetoothSocket(RFCOMM)
    while server_socket_bound:
        try:
            server_sock.bind(("", PORT_ANY))
            server_socket_bound = False
        except OSError as err:
            print("Server socket could not be bound to any Bluetooth port. Ensure Bluetooth is active.")
            time.sleep(2)
    server_sock.listen(1)


    # Create the server thread and start it
    args_tuple = ()
    server_thread = StoppableThread(target=bluetooth_server_start, args=args_tuple)
    server_thread.start()

    print("Bluetooth server has been started")

    # While the server thread is running, main thread sleeps.
    while is_server_running:
        try:
            # Check if server is running every 2s to exit automatically
            time.sleep(2)
        except KeyboardInterrupt:
            # If Ctrl+C is pressed, tell the server to stop and exit.
            print('KeyboardInterrupt exception caught --> Stopping the server...')
            server_thread.stop()
            server_thread.join()
            exit(0)

    print("Exitting...")



# The server only saves the extension, the 'name' of the file is always the same, and it is defined in FIXED_FILENAME.
# NOTE: if there is no extension, then the full received filenamme is used. Useful for testing.
def compose_file_full_path(recv_filename):
    extension = ""
    extension_dot_idx = recv_filename.rfind(".")
    if extension_dot_idx == -1:
        extension = ""
        filename = recv_filename
    else:
        extension = recv_filename[extension_dot_idx:]
        filename = FIXED_FILENAME

    return FOLDER_PATH+"/"+filename+extension



def bluetooth_server_start():
    # Use global vars (and allow modifications)
    global server_sock
    global client_sock
    global is_server_running
    global server_thread

    # Set server running to true so the main thread loop does not exit automatically
    is_server_running = True

    port = server_sock.getsockname()[1]

    # Make the server visible for other bluetooth devices
    advertise_service(server_sock, "SampleServer",
                        service_id = UUID,
                        service_classes = [ UUID, SERIAL_PORT_CLASS ],
                        profiles = [ SERIAL_PORT_PROFILE ], 
                        protocols = [ OBEX_UUID ] 
                        )

    # Keep trying to stablish connections forever
    while True:
        print("Waiting for connection on RFCOMM channel %d..." % port)

        client_sock, client_info = server_sock.accept()
        print("Accepted connection from ", client_info, "\n")

        # (Re)initialize the variables to start receiving data
        phase = PHASE_GETTING_NAME_LENGTH

        recv_buf = None

        filename_length_size = 0
        filename_length = 0
        filename = None
        data = None
        data_size = 0

        file_full_path = None
        file_handle = None
        write_success = False

        # While in a connection, keep receiving data, which format is: (filename_size, filename, filedata).
        while True:
            try:
                if phase == PHASE_GETTING_NAME_LENGTH:
                    # Get data as a big-endian unsigned integer
                    recv_buf = client_sock.recv(SIZE_OF_NAME_LENGTH)
                    filename_length_size = len(recv_buf)
                    
                    filename_length = int.from_bytes(recv_buf, byteorder='big', signed=False)   #filename_length = int(recv_buf[0])     # This is only valid for 1 byte
                    # if filename_length_size != SIZE_OF_NAME_LENGTH:
                    #   print("Error: the transmission did not adhere to the secureworld protocol specification. Filename length must be contained in "+str(SIZE_OF_NAME_LENGTH)+" Bytes, but was contained in " + str(filename_length_size) + ".")
                    #   break   # Error following the transfer protocol
                    if filename_length > MAX_FILENAME_LENGTH_ALLOWED:
                        print("Error: the transmission did not adhere to the secureworld protocol specification. Filename must not be greater than "+str(MAX_FILENAME_LENGTH_ALLOWED)+" Bytes, but was " + str(filename_length) + ".")
                        break   # Error following the transfer protocol
                    print("filename_length: ", filename_length)
                    phase = PHASE_GETTING_NAME


                elif phase == PHASE_GETTING_NAME:
                    # Get data as a string (in UTF-8)
                    recv_buf = client_sock.recv(filename_length)
                    filename = recv_buf.decode("utf-8")
                    if len(recv_buf) != filename_length:
                        print("Error: the transmission did not adhere to the secureworld protocol specification. Filename length must be equal to the value contained in the filename_length field ("+str(filename_length)+" Bytes).")
                        break   # Error following the transfer protocol

                    # Compose the final path name
                    file_full_path = compose_file_full_path(filename)
                    print("file_full_path: ", file_full_path)

                    # Check file existence
                    if os.path.exists(file_full_path):
                        print("The file '" + file_full_path + "' already exists. Overwriting it...")
                    else:
                        print("The file '" + file_full_path + "' does not exists. Creating it...")

                    # Open the file for writing in binary mode. If file exists, its data is truncated and it is overwritten. If it does not exist, it is created.
                    while not file_handle:
                        try:
                            file_handle = open(file_full_path,"wb")
                        except IOError:
                            print("Could not create the file '" + file_full_path + "'.")
                        else:
                            print("File '" + file_full_path + "' successfully created.")

                    phase = PHASE_GETTING_DATA  #PHASE_GETTING_FILE_SIZE


                elif phase == PHASE_GETTING_DATA:
                    # Get data as a bytes (no conversion)
                    recv_buf = client_sock.recv(MAX_CHUNK_DATA_SIZE)
                    data = recv_buf
                    data_size = len(data)
                    print("data: %s" % data)
                    print("data_size: %d" % data_size)

                    # Close connection with the client when 0 bytes are received
                    if data_size == 0:
                        break

                    # Keep trying to write the data until the write is successful
                    write_success = False
                    while not write_success:
                        try:
                            print("writing data to file")
                            file_handle.write(data)
                        except:
                            print("Error trying to write data chunk to file. Retrying...")
                            sleep(0.5)
                        else:
                            write_success = True

            except IOError:
                pass

        print("Transmission finished")
        server_thread.close_client_socket()
        try:
            file_handle.close()
        except:
            pass



    # This should never happen. Even if client disconnects, server should still keep running
    # This code will never be reached
    print("Conection dropped")
    server_thread.stop(False)



if __name__ == '__main__':
    main()

