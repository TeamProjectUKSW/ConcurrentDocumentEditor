# ConcurrentDocumentEditor

A lightweight collaborative text editor for local networks (LAN).  
It uses **UDP broadcast** for peer discovery + messaging, and a **CRDT (RGA / Replicated Growable Array)** to merge concurrent edits without conflicts.

## Features

- Local text editing (open/save/save as), themes, font selection (PyQt6 GUI).
- Real-time collaboration on the same document over LAN using UDP. 
- Conflict-free merging via CRDT (RGA) with unique IDs *(Lamport counter + client ID)*. 
- Join-in-progress support via **snapshot sync** (new peer receives the full CRDT state). 
- Desync detection (periodic state hash check) and automatic snapshot request/send.
- Compression and chunking for large snapshot payloads (gzip + base64 + fragmentation). 

## Project structure

- `main.py` – app entrypoint (creates `QApplication`, sets window icon, shows editor).
- `editor.py` – base GUI layer (`BaseTextEditor`): toolbar, themes, file I/O. 
- `concurrency.py` – distributed logic (`ConcurrentTextEditor`): UDP networking, peer management, CRDT integration, snapshots, consistency checks.  
- `crdt.py` – RGA CRDT implementation (`RgaCrdt`).
- `requirements.txt` – Python dependencies. 


## Requirements

- Python 3.x (must be compatible with PyQt6 6.10.1)  
- Dependencies from `requirements.txt`: `PyQt6`, `netifaces`, etc. 

### Network assumptions

- All collaborators are in the **same local network** (same broadcast domain / VLAN).
- UDP broadcast is allowed on the network.
- Firewall allows **UDP 5005** (see below). 

## Installation

### 1) Clone / download

Put the project in a local folder, for example:

```bash
git clone <repo-url>
cd ConcurrentDocumentEditor
```

### 2) (Recommended) Create a virtual environment

**Linux/macOS**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell)**
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3) Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run

```bash
python main.py
```

`main.py` sets the app icon as `icon/icon_256.png`. If your repository layout differs, create the folder `icon/` and place the icon file there. 

## How to use (single user)

1. **Open** – load a text file into the editor.
2. Edit the content (plain text).
3. **Save** / **Save as** – write to disk.
4. Optional:
   - **Change font**
   - Choose one of the **themes** from the dropdown.

## How to collaborate (multi-user)

### Start a session (host / inviter)

1. Open or write the document you want to share.
2. Click **Share**. The app will broadcast an invite on the LAN.

### Join a session (invitee)

1. Run the app on another computer in the same LAN.
2. When an invite dialog appears, click **Yes**.
3. If you have unsaved local changes, you’ll be asked whether to save, discard, or cancel before joining.

After joining:
- Edits are sent as CRDT operations (`CRDT_INSERT` / `CRDT_DELETE`) and merged locally.
- A full **snapshot** can be sent to synchronize a late joiner or recover from detected desync. 

### Leave a session

Click **Disconnect**. A `PEER_LEAVE` message is broadcast and the editor continues offline.

## Ports and firewall

The editor listens on **UDP port 5005** by default and uses broadcast to discover peers.

### Debian/Ubuntu (UFW)

```bash
sudo ufw allow 5005/udp
```

### Other systems

Open UDP 5005 in your OS firewall settings (inbound + outbound) for your local network profile.

## Protocol overview (for documentation)

Messages are JSON dictionaries sent via UDP. Examples include:
- `INVITE` / `INVITE_ACCEPT` – discovery and join flow.
- `PEER_ANNOUNCE` / `PEER_LEAVE` – peer list updates. 
- `CRDT_INSERT` / `CRDT_DELETE` – incremental edits.
- `SNAPSHOT` / `REQUEST_SNAPSHOT` – full-state synchronization.
- `STATE_CHECK` – periodic consistency checks (hash + node count).

Large payloads are:
1) gzip-compressed,
2) optionally chunked into smaller UDP packets (`CHUNK` messages),
3) with base64 for binary chunk data. 

## Troubleshooting

### “No multiuser work enabled…” / no peers discovered
The app derives your local IP and broadcast address using `netifaces` and ignores loopback/link-local interfaces. If it can’t find a usable interface, collaboration won’t work. 

Fixes:
- Make sure you’re connected to a LAN (Wi‑Fi/Ethernet).
- Ensure the network allows UDP broadcast.
- Check firewall rules (UDP 5005).

### Invite pops up but joining doesn’t sync
- If the network drops packets, snapshots may be needed; the app can request/send snapshots when it detects desynchronization.
- If you’re on different subnets/VLANs, UDP broadcast will usually not traverse routers.

### macOS / Windows firewall
Allow the Python executable (or packaged app) to receive incoming UDP connections on private networks.

## Known issues

- **Font resets when switching themes**: theme change overwrites widget styling and the font settings revert to defaults. This is listed as an identified issue in the report. 

## Tested platforms

System testing reported working on **Windows, Linux, and macOS** with up to 4 machines collaborating.  

## Credits

Members of the project:
- Jan Lotycz – project manager  
- Rafał Bryk – report  
- Bartłomiej Kalinowski – code supervision  
- Wiktor Jabłoński, Michał Meresiński – code

---
