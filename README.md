# iss_position_checker

You can check app live here : https://iss.outpacelab.com/

# ISS Position Tracker 🚀

A web application that displays the current position of the International Space Station (ISS) on a live map, shows the number of people currently in space, and calculates upcoming ISS passes over a selected location.

The application is built with **FastAPI**, uses **Skyfield** for orbital calculations, and is deployed behind **Nginx** with HTTPS support.

---

## ✨ Features

* 🌍 Live ISS position on an interactive map
* 👨‍🚀 Current number of people in space
* 📋 Clickable astronaut list with:

  * Name
  * Agency
  * Country
  * Photo (if available)
  * Wikipedia link
* 📡 Automatic calculation of:

  * ISS velocity (based on coordinate delta)
  * Orbital period
  * Average altitude
* 🛰️ Upcoming ISS passes over specific coordinates
* 🇵🇱 Localized output for Poland (Europe/Warsaw timezone)

---

## 🧱 Tech Stack

* **Python 3.12**
* **FastAPI**
* **Uvicorn**
* **Skyfield**
* **Requests**
* **Nginx (reverse proxy)**
* **Certbot (HTTPS)**

---

## 📦 Installation (Local Development)

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/iss_position_checker.git
cd iss_position_checker
```

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run application

```bash
uvicorn app:app --reload
```

Open in browser:

```
http://127.0.0.1:8000
```

---

## 🚀 Production Deployment (Linux VPS)

### 1. Create virtual environment

```bash
python3 -m venv /srv/venvs/iss
source /srv/venvs/iss/bin/activate
pip install -r requirements.txt
deactivate
```

### 2. Systemd service

Create:

```
/etc/systemd/system/iss.service
```

```ini
[Unit]
Description=ISS app (FastAPI)
After=network.target

[Service]
User=kem
Group=kem
WorkingDirectory=/srv/apps/iss/iss_position_checker
Environment=PYTHONUNBUFFERED=1
ExecStart=/srv/venvs/iss/bin/uvicorn app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now iss
```

---

## 🌐 Nginx Reverse Proxy

Example configuration:

```nginx
server {
    listen 80;
    server_name iss.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable site and reload nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Then issue SSL certificate:

```bash
sudo certbot --nginx -d iss.yourdomain.com
```

---

## 📊 Data Sources

* ISS current position:
  [http://api.open-notify.org/iss-now.json](http://api.open-notify.org/iss-now.json)

* People in space:
  [https://corquaid.github.io/international-space-station-APIs/JSON/people-in-space.json](https://corquaid.github.io/international-space-station-APIs/JSON/people-in-space.json)

* Orbital calculations:
  Skyfield TLE data

---

## 🔒 Security Considerations

* Application listens only on `127.0.0.1`
* Public access is handled by Nginx
* HTTPS enabled via Certbot
* Firewall (UFW) allows only:

  * 22 (SSH)
  * 80 (HTTP)
  * 443 (HTTPS)

---

## 🧠 Future Improvements

* User-input location (address-based geocoding)
* ISS visibility calculation (sunlight conditions)
* Push notifications
* Telegram bot integration
* Rate limiting for public API usage

---

## 📜 License

MIT License
