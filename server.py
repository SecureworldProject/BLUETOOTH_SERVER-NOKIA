import time
from bluetooth import *
import threading
import os
#import multiprocessing
#import select


server_sock = None
client_sock = None
server_thread = None
is_server_running = False

SIZE_OF_NAME_LENGTH = 1             # 1 Bytes for the length of the filename(and extension) in bytes (min: 1, max: 256)
SIZE_OF_FILE_SIZE = 4               # 4 Bytes for the size of the file in bytes (min: 0, max: 4.294.967.295)

MAX_CHUNK_SIZE = 64*1024            # 64 KiB. The maximum size of each chunk that will be read from the socket
MAX_FILENAME_LENGTH_ALLOWED = 150   # 150 Bytes for the name and its extension (was not set to 255)
MAX_FILE_SIZE_ALLOWED = 42949672956 # 2^32 - 1  =  4.294.967.296 - 1  =  4.294.967.295

UUID = "94f39d29-7d6d-437d-973b-fba39e49d4ee"


# Get environment variables
FOLDER_PATH = os.getenv('SECUREMIRROR_CAPTURES')

# class ReceivingPhase(Enum):
#   GETTING_NAME_SIZE   = 0
#   GETTING_NAME        = 1
#   GETTING_FILE_SIZE   = 2
#   GETTING_DATA        = 3
#   DONE                = 4
# ReceivingPhase = {
#   0: "GETTING_NAME_SIZE"
#   1: "GETTING_NAME"
#   2: "GETTING_FILE_SIZE"
#   3: "GETTING_DATA"
#   4: "DONE"
# }
PHASE_GETTING_NAME_LENGTH   = "PHASE_GETTING_NAME_LENGTH"
PHASE_GETTING_NAME          = "PHASE_GETTING_NAME"
PHASE_GETTING_FILE_SIZE     = "PHASE_GETTING_FILE_SIZE"
PHASE_GETTING_DATA          = "PHASE_GETTING_DATA"
PHASE_DONE                  = "PHASE_DONE"



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
            # Check if server is running every 5s to exit automatically
            time.sleep(2)
        except KeyboardInterrupt:
            # If Ctrl+C is pressed, tell the server to stop and exit.
            print('KeyboardInterrupt exception caught --> Stopping the server...')
            server_thread.stop()
            server_thread.join()
            exit(0)

    print("Exitting...")


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
                       
    print("Waiting for connection on RFCOMM channel %d..." % port)

    client_sock, client_info = server_sock.accept()
    print("Accepted connection from ", client_info, "\n")

    phase = PHASE_GETTING_NAME_LENGTH

    chunk_size = 0
    chunk_data = None

    filename_length = 0
    filename = None
    remaining_data_size = 0
    file_size = 0
    data = None

    file_full_path = None
    file_handle = None
    write_success = False

    while True:
        try:
            if phase == PHASE_GETTING_NAME_LENGTH:
                # Get data as a big-endian unsigned integer
                filename_length = int.from_bytes(client_sock.recv(SIZE_OF_NAME_LENGTH), byteorder='big', signed=False)  #client_sock.recv(SIZE_OF_NAME_LENGTH)
                if filename_length != SIZE_OF_NAME_LENGTH:
                    print("Error: the transmission did not adhere to the secureworld protocol specification. Filename length must be contained in "+str(SIZE_OF_NAME_LENGTH)+" Bytes.")
                    break   # Error following the transfer protocol
                if filename_length > MAX_FILENAME_LENGTH_ALLOWED:
                    print("Error: the transmission did not adhere to the secureworld protocol specification. Filename must not be greater than "+str(MAX_FILENAME_LENGTH_ALLOWED)+" Bytes.")
                    break   # Error following the transfer protocol
                print("filename_length: ", filename_length)
                phase = PHASE_GETTING_NAME


            elif phase == PHASE_GETTING_NAME:
                # Get data as a string (in UTF-8)
                filename = client_sock.recv(filename_length).decode("utf-8")
                if len(filename) != filename_length:
                    print("Error: the transmission did not adhere to the secureworld protocol specification. Filename length must be equal to the value contained in the filename_length field ("+str(filename_length)+" Bytes).")
                    break   # Error following the transfer protocol
                print("filename: ", filename)
                file_full_path = FOLDER_PATH+"/"+filename
                phase = PHASE_GETTING_FILE_SIZE


            elif phase == PHASE_GETTING_FILE_SIZE:
                # Get data as a big-endian unsigned integer
                file_size = int.from_bytes(client_sock.recv(SIZE_OF_FILE_SIZE), byteorder='big', signed=False)  #client_sock.recv(SIZE_OF_FILE_SIZE)
                if file_size != SIZE_OF_FILE_SIZE:
                    print("Error: the transmission did not adhere to the secureworld protocol specification. File size must be contained in "+str(SIZE_OF_FILE_SIZE)+" Bytes.")
                    break   # Error following the transfer protocol
                if file_size > MAX_FILE_SIZE_ALLOWED:   # This will never happen as the max file size is the maximum value storable in 4 bytes
                    print("Error: the transmission did not adhere to the secureworld protocol specification. File size must not be greater than "+str(MAX_FILE_SIZE_ALLOWED)+" Bytes.")
                    break   # Error following the transfer protocol
                print("file_size: ", file_size)
                remaining_data_size = file_size
                phase = PHASE_GETTING_DATA

                # Check file existence
                if os.path.exists(file_full_path):
                    print("The file " + file_full_path + " already exists. Overwriting it...")
                else:
                    print("The file " + file_full_path + " does not exists. Creating it...")

                # Open the file for writing in binary mode. If file exists, its data is truncated and it is overwritten. If it does not exist, it is created.
                while not file_handle:
                    try:
                        file_handle = open(file_full_path,"wb")
                    except IOError:
                        print("Could not create the file " + file_full_path + ".")
                    else:
                        print("File " + file_full_path + " successfully created.")


            elif phase == PHASE_GETTING_DATA:
                print("remaining_data_size: ", remaining_data_size)
                chunk_size = min(remaining_data_size, MAX_CHUNK_SIZE)

                # Get data as a bytes (no conversion)
                chunk_data = client_sock.recv(chunk_size)
                if len(chunk_data) != chunk_size:
                    print("Error: the transmission did not adhere to the secureworld protocol specification. File size must be equal to the value contained in the file_size field ("+str(file_size)+" Bytes).")
                    break   # Error following the transfer protocol
                print("Received chunk_data[%s]" % chunk_data)

                # Keep trying to write the data until the write is successful
                write_success = False
                while not write_success:
                    try:
                        file_handle.write(chunk_data)
                    except:
                        print("Error trying to write data chunk to file.")
                        sleep(0.5)
                    else:
                        write_success = True
                remaining_data_size -= chunk_size

                if remaining_data_size == 0:
                    phase = PHASE_DONE


            elif phase == PHASE_DONE:
                print("File correctly received. Ready to receive more files.")
                phase = PHASE_GETTING_NAME_LENGTH

                chunk_size = 0
                chunk_data = None

                filename_length = 0
                filename = None
                remaining_data_size = 0
                file_size = 0
                data = None

                file_full_path = None
                file_handle.close()
                file_handle = None


        except IOError:
            pass

    # This should never happen, even if client disconnects, server should still keep running
    # This code will never be reached
    print("Conection dropped")
    server_thread.stop(False)




if __name__ == '__main__':
    main()

