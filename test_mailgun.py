import os
import requests

def send_simple_message():
    return requests.post(
        "https://api.mailgun.net/v3/sandbox2d364b1e618b40d2a0aa2d890b082b29.mailgun.org/messages",
        auth=("api", os.getenv('API_KEY', 'edfb56d506e9111b0c94174c35b14ab1-4293193c-f076c70f')),
        data={"from": "Mailgun Sandbox <postmaster@sandbox2d364b1e618b40d2a0aa2d890b082b29.mailgun.org>",
              "to": "Rafael Da Hora De Sousa <probuxltda@probux.net.br>",
              "subject": "Hello Rafael Da Hora De Sousa",
              "text": "Congratulations Rafael Da Hora De Sousa, you just sent an email with Mailgun! You are truly awesome!"})

if __name__ == '__main__':
    response = send_simple_message()
    print("Status:", response.status_code)
    print("Response:", response.text)
