# ** WORK IN PROGRESS **
NOT FULLY FUNCTIONAL AT THIS TIME

# **AxePoolSetter**

AxePoolSetter is an internal, web-based application designed to monitor and manage Bitcoin mining devices (specifically Nerdminers, Bitaxes, and similar devices) on a local network. It allows for network scanning to discover devices, manual addition of devices, and batch-updating of stratum configurations.

This application is built with a Python (Flask) backend and a simple HTML/Tailwind CSS frontend, and is containerized with Docker for easy deployment.

## **Features**

* **Network Discovery:** Scan a local network subnet (e.g., 192.168.1.) to find active miners.  
* **Device Management:** Manually add devices by IP address. The device list is persisted in a local SQLite database.  
* **Live Dashboard:** View all discovered devices, their hostnames, IP addresses, online status, hashrate, temperature, and current stratum settings.  
* **Quick Links:** Clickable IP addresses link directly to each device's web interface.  
* **Global Configuration:** A central form to set and apply stratum (primary and fallback) configurations to all online devices with a single click.

## **File Structure**

miner\_monitor/  
├── docker-compose.yaml       \# Docker Compose file for orchestration  
├── README.md                 \# This file  
├── .gitignore                \# Git ignore file  
└── backend/  
    ├── Dockerfile            \# Dockerfile for the backend app  
    ├── app.py                \# The core Flask application  
    ├── requirements.txt      \# Python dependencies  
    └── static/  
        └── index.html        \# The complete frontend (HTML, CSS, JS)

## **How to Run**

### **Prerequisites**

* [Docker](https://www.docker.com/get-started)  
* [Docker Compose](https://docs.docker.com/compose/install/)

### **Installation & Launch**

1. **Clone the Repository**  
   git clone https://github.com/andewkuehne/AxePoolSetter
   cd AxePoolSetter

2. Build and Run with Docker Compose  
   Open a terminal in the project's root directory (AxePoolSetter) and run:  
   docker-compose up \--build

   This command will:  
   * Build the backend Docker image from the Dockerfile.  
   * Start the application container.  
   * Use network\_mode: "host" to give the container access to your local network for scanning.  
   * Create a Docker volume named miner\_data to persist the devices.db file, saving your manually added devices.  
3. Access the Application  
   Once the container is running, open your web browser and navigate to:  
   **http://localhost:5005**

## **Author**

* Andrew Kuehne

## **License**

This project is licensed under the MIT License.