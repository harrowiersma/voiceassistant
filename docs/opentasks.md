# Open Tasks: External Service Setup

Tasks that require manual configuration outside the Voice Secretary dashboard. Complete these before the system can handle real calls.

---

## 1. DIDWW — Inbound SIP Trunk

DIDWW provides the phone number and SIP trunk that routes calls to your Pi.

- [ ] Create DIDWW account at https://www.didww.com
- [ ] Purchase a phone number (choose country/area code)
- [ ] Create a SIP trunk:
  - Go to **Trunks → Create Trunk**
  - Type: **SIP Registration**
  - Note the SIP server address (e.g., `sip.didww.com`)
  - Set a trunk username and password
  - Set codec priority: **G.711 u-law (PCMU)** first, then **G.711 a-law (PCMA)**
- [ ] Assign the phone number to the trunk:
  - Go to **DID Numbers → your number → Voice Settings**
  - Point it to the trunk you created
- [ ] Configure your router/firewall:
  - Forward UDP port **5060** (SIP signaling) to the Pi's LAN IP
  - Forward UDP ports **10000-20000** (RTP media) to the Pi's LAN IP
  - Or use a DMZ/public IP if available
- [ ] Enter trunk credentials in Voice Secretary dashboard:
  - Go to **SIP Settings**
  - Fill in: server, port (5060), username, password
  - Click **Save** then **Apply to Asterisk**
- [ ] Test: call your DIDWW number from a mobile phone

**Alternative providers:** Twilio SIP Trunking, VoIP.ms, Flowroute, Telnyx — same SIP registration approach.

---

## 2. Microsoft Graph — Teams Presence & Calendar

Required for checking your Teams availability and calendar free slots.

### Azure App Registration
- [ ] Go to https://portal.azure.com → **Azure Active Directory → App registrations → New registration**
- [ ] Name: `Voice Secretary`
- [ ] Supported account types: **Single tenant** (your org only)
- [ ] Redirect URI: leave blank for now (we use device code flow)
- [ ] Note the **Application (client) ID**
- [ ] Note the **Directory (tenant) ID**

### API Permissions
- [ ] Go to **API permissions → Add a permission → Microsoft Graph**
- [ ] Add **Delegated** permissions:
  - `Presence.Read` — read your Teams presence status
  - `Calendars.Read` — read your calendar events
  - `User.Read` — basic profile info
- [ ] Click **Grant admin consent** (requires admin role)

### Client Secret
- [ ] Go to **Certificates & secrets → New client secret**
- [ ] Description: `Voice Secretary`
- [ ] Expiry: 24 months (set a calendar reminder to renew)
- [ ] **Copy the secret value immediately** (shown only once)

### Enter in Dashboard
- [ ] Go to **Availability → MS Graph Setup**
- [ ] Enter: Client ID, Client Secret, Tenant ID
- [ ] Click **Save**

### OAuth Token (first-time auth)
- [ ] The dashboard will show an OAuth authorization link
- [ ] Click it, sign in with your Microsoft account
- [ ] Grant the requested permissions
- [ ] Token is stored in the database (auto-refreshes)

---

## 3. Google Calendar (per-persona, optional)

Required only for personas that use Google Calendar instead of MS Graph.

### Google Cloud Project
- [ ] Go to https://console.cloud.google.com → **Create Project**
- [ ] Name: `Voice Secretary`
- [ ] Enable the **Google Calendar API**:
  - Go to **APIs & Services → Library**
  - Search "Google Calendar API" → **Enable**

### OAuth Credentials
- [ ] Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
- [ ] Application type: **Web application**
- [ ] Name: `Voice Secretary`
- [ ] Authorized redirect URIs: `http://voicesec.local:8080/auth/google/callback`
- [ ] Note the **Client ID** and **Client Secret**

### OAuth Consent Screen
- [ ] Go to **APIs & Services → OAuth consent screen**
- [ ] User type: **Internal** (your org) or **External** (for personal accounts)
- [ ] App name: `Voice Secretary`
- [ ] Scopes: add `https://www.googleapis.com/auth/calendar.readonly`
- [ ] Add your email as a test user (if External)

### Enter in Dashboard
- [ ] Go to **Personas → Edit persona → Calendar Type: Google**
- [ ] Store the Google OAuth credentials in the persona's calendar config
- [ ] Complete the OAuth flow to get an access/refresh token

---

## 4. SMTP Email — Call Summary Notifications

Required for sending email summaries after calls.

### Option A: Gmail App Password
- [ ] Go to https://myaccount.google.com/security
- [ ] Enable **2-Step Verification** (required for app passwords)
- [ ] Go to **App passwords** → Generate one for "Mail"
- [ ] Enter in dashboard (**Actions** screen):
  - SMTP Server: `smtp.gmail.com`
  - Port: `587`
  - Username: your Gmail address
  - Password: the 16-character app password
  - From: your Gmail address
  - To: your email (or a different one)

### Option B: Custom SMTP Server
- [ ] Get SMTP credentials from your email provider
- [ ] Enter in dashboard (**Actions** screen):
  - SMTP Server: provider's SMTP host
  - Port: 587 (TLS) or 465 (SSL)
  - Username / Password
  - From / To addresses

### Option C: Microsoft 365 SMTP (if using MS Graph)
- [ ] SMTP server: `smtp.office365.com`
- [ ] Port: `587`
- [ ] Username: your M365 email
- [ ] Password: your M365 password (or app password if MFA enabled)

### Test
- [ ] Go to **Actions** screen → enter settings → **Save**
- [ ] Make a test call — check if email arrives

---

## 5. Outbound SIP Trunk (optional)

Only needed if you want to use a different provider for outbound calls (forwarding, test calls) than your inbound trunk.

- [ ] Create a second DIDWW trunk (or use a different provider)
- [ ] Enter credentials in **SIP Settings → Outbound SIP Trunk**
- [ ] If not configured, the inbound trunk is used for outbound calls too

---

## 6. Internal SIP Extensions (optional)

Register SIP phones/softphones on your LAN for call forwarding.

- [ ] Install a SIP softphone app:
  - Desktop: **MicroSIP** (Windows), **Telephone** (macOS), **Linphone** (cross-platform)
  - Mobile: **Linphone**, **Zoiper**, **Groundwire**
- [ ] In Voice Secretary dashboard → **SIP Settings → Internal Extensions**:
  - Enter extension name (e.g., `desk-phone`) and password
  - Click **Save** then **Apply to Asterisk**
- [ ] In the softphone app:
  - SIP server: your Pi's LAN IP (e.g., `192.168.1.100`)
  - Username: the extension name
  - Password: the extension password
  - Port: 5060
- [ ] Test: call your DIDWW number — it should ring the softphone first

---

## 7. Pi Hardware Setup

- [ ] Raspberry Pi 5 (8GB) with active cooler
- [ ] NVMe SSD (via Pi 5 HAT) or high-quality SD card (A2 rated)
- [ ] Flash the Voice Secretary image: `make image` → Raspberry Pi Imager
- [ ] Connect Pi to LAN via Ethernet (recommended) or WiFi
- [ ] Boot and find IP: `ping voicesec.local` or check router DHCP leases
- [ ] Open `http://voicesec.local:8080` → login with `admin` / `voicesec`
- [ ] **Change the default password** immediately (System screen)

---

## 8. First-Run Checklist

After flashing and booting:

1. [ ] Login to dashboard, change password
2. [ ] Configure SIP trunk (DIDWW credentials)
3. [ ] Apply Asterisk config
4. [ ] Set up persona (company name, greeting, personality)
5. [ ] Add knowledge rules (office hours, address, common questions)
6. [ ] Configure MS Graph or Google Calendar (optional)
7. [ ] Set availability rules (business hours, presence mapping)
8. [ ] Configure email notifications (SMTP)
9. [ ] Make a test call from your mobile
10. [ ] Verify: greeting plays, AI responds, message taken, email sent

---

## 9. Ongoing Maintenance

- [ ] Renew MS Graph client secret before expiry (check Azure portal)
- [ ] Renew Google OAuth tokens if they expire
- [ ] Monitor CPU temperature via System screen (should stay below 70°C)
- [ ] Backup config periodically (System → Download Backup)
- [ ] Check call log for blocked/spam numbers — add to Call Blocking
- [ ] Update Ollama models when newer versions are available
