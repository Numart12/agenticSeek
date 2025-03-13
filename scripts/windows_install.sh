#!/bin/bash

echo "Starting installation for Windows..."

# Install Python dependencies from requirements.txt
pip3 install -r requirements.txt

# Install Selenium
pip3 install selenium

echo "Note: pyAudio installation may require additional steps on Windows."
echo "Please install portaudio manually (e.g., via vcpkg or prebuilt binaries) and then run: pip3 install pyaudio"
echo "Also, download and install chromedriver manually from: https://sites.google.com/chromium.org/driver/getting-started"
echo "Place chromedriver in a directory included in your PATH."

echo "Installation partially complete for Windows. Follow manual steps above."