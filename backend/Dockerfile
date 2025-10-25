# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend application code
COPY . .

# Make port 5005 available to the world outside this container
# Note: With network_mode: "host" in docker-compose, this is more for documentation.
# The app will bind directly to the host's port 5005.
EXPOSE 5005

# Define environment variable
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0

# Command to run the application using Gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:5005", "--workers", "4", "app:app"]
