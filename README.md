# BhashaShield

Multilingual scam-call safety companion built on Sarvam AI (Saaras speech-to-text, Sarvam 105B analysis, Bulbul text-to-speech).
It identifies potential warning signs only; it cannot guarantee that a call is fraudulent or legitimate. It never records or monitors calls in the background.

## Run
```
pip install -r requirements.txt
cp .env.example .env        # then paste your SARVAM_API_KEY into .env
uvicorn server:app --port 8000
```
Open http://localhost:8000. The key stays on the server and is never sent to the browser. `.env` is git-ignored.
