# Use an official lightweight Python runtime
FROM python:3.11-slim

# Set the system port environment variable for Cloud Run compliance
EXPOSE 8080

# Establish the internal working directory
WORKDIR /app

# Copy the application assets into the container
COPY . .

# Install production dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Launch Streamlit bound to Cloud Run's required port and host settings
ENTRYPOINT ["streamlit", "run", "dashboard.py", "--server.port=8080", "--server.address=0.0.0.0"]