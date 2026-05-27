import socket

# This script listens to raw traffic on Port 8000 
# to see if the machine is even sending data.

def start_sniffer():
    # Use the Laptop's LAN IP
    IP = "192.168.137.1"
    PORT = 8000
    
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((IP, PORT))
        server.listen(5)
        print(f"[*] Sniffer active on {IP}:{PORT}")
        print("[*] Waiting for machine to connect...")
        
        while True:
            client, addr = server.accept()
            print(f"[!] CONNECTION RECEIVED from {addr}")
            data = client.recv(1024)
            if data:
                print(f"[<] DATA: {data.decode('utf-8', errors='ignore')}")
            client.send(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nOK\n")
            client.close()
    except Exception as e:
        print(f"[ERROR] {e}")

if __name__ == "__main__":
    start_sniffer()
