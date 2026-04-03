PERSONA_DEFAULTS = {
    "persona.company_name": "",
    "persona.greeting": "Hello, you've reached {company}. How can I help you today?",
    "persona.personality": "You are a professional and friendly phone secretary. Be helpful, concise, and courteous.",
    "persona.unavailable_message": "I'm sorry, no one is available to take your call right now. May I take a message?",
}

SIP_DEFAULTS = {
    "sip.inbound_server": "",
    "sip.inbound_username": "",
    "sip.inbound_password": "",
    "sip.inbound_port": "5060",
    "sip.outbound_server": "",
    "sip.outbound_username": "",
    "sip.outbound_password": "",
    "sip.outbound_port": "",
    "sip.forward_number": "",
}

AI_DEFAULTS = {
    "ai.stt_model": "vosk-small",
    "ai.llm_model": "llama3.2:1b",
    "ai.tts_voice": "en-us-amy-medium",
    "ai.response_timeout": "10",
    "ai.max_call_duration": "300",
}

ACTIONS_DEFAULTS = {
    "actions.smtp_server": "",
    "actions.smtp_port": "587",
    "actions.smtp_username": "",
    "actions.smtp_password": "",
    "actions.email_to": "",
    "actions.email_from": "",
    "actions.notify_on": "message_only",
}

AVAILABILITY_DEFAULTS = {
    "availability.manual_override": "auto",
    "availability.business_hours_start": "09:00",
    "availability.business_hours_end": "17:00",
    "availability.action_available": "forward",
    "availability.action_busy": "take_message",
    "availability.action_dnd": "take_message",
    "availability.action_away": "take_message",
    "graph.client_id": "",
    "graph.client_secret": "",
    "graph.tenant_id": "",
}
