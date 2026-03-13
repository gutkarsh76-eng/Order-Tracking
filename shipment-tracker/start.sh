#!/bin/bash
# Install dependencies and start the tracking server
pip install -r requirements.txt -q
echo "Starting server at http://localhost:8080"
python server.py
