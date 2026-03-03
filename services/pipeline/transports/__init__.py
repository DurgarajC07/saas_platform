"""
Transports package for the Pipeline Service.

Each module wraps a Pipecat transport or implements one from scratch:

  websocket.py    WebSocketServerTransport  — browser SDK / WebSocket clients
  webrtc.py       WebRTCTransport           — aiortc ICE/DTLS for browser WebRTC
  twilio.py       TwilioTransport           — Pipecat built-in, PSTN telephony
"""
