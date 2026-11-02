"""BhashaShield backend. The Sarvam key is read from the environment and never sent to the browser."""
import base64, json, os, re
from pathlib import Path
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

HERE = Path(__file__).parent
if (HERE / ".env").exists():  # tiny .env loader, no extra dependency
    for ln in (HERE / ".env").read_text().splitlines():
        if "=" in ln and not ln.startswith("#"):
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

CHAT = os.environ.get("SARVAM_CHAT_MODEL", "sarvam-105b")
STT = os.environ.get("SARVAM_STT_MODEL", "saaras:v4")
TTS = os.environ.get("SARVAM_TTS_MODEL", "bulbul:v4-flash")
TTS_SPEAKER = os.environ.get("SARVAM_TTS_SPEAKER")  # optional; omitted = model default
LANGS = {"mr": ("Marathi", "mr-IN"), "hi": ("Hindi", "hi-IN"), "en": ("English", "en-IN")}
EXTS = {".wav", ".mp3", ".aac", ".ogg", ".opus", ".flac", ".m4a", ".mp4", ".webm", ".amr", ".wma"}
app = FastAPI(title="BhashaShield")


def client():
    from sarvamai import SarvamAI
    if not os.environ.get("SARVAM_API_KEY"):
        raise RuntimeError("SARVAM_API_KEY is not set on the server.")
    return SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])


def fail(msg, code=502):
    return JSONResponse({"error": msg}, status_code=code)


@app.get("/")
def index():
    return FileResponse(HERE / "index.html")


@app.get("/api/status")
def status():
    return {"live": bool(os.environ.get("SARVAM_API_KEY")), "models": {"chat": CHAT, "stt": STT, "tts": TTS}}


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = Form("auto")):
    ext = Path(file.filename or "").suffix.lower()
    data = await file.read()
    if ext not in EXTS:
        return fail(f"Unsupported file type '{ext or '?'}'. Try WAV, MP3, M4A, OGG, FLAC or AAC.", 415)
    if len(data) < 1000:
        return fail("This recording looks empty. Please choose a longer clip.", 422)
    if len(data) > 25_000_000:
        return fail("File is too large (25 MB max).", 413)
    kw = {"language_code": LANGS[language][1]} if language in LANGS else {}
    try:
        r = client().speech_to_text.transcribe(file=(file.filename, data, file.content_type or "audio/wav"),
                                              model=STT, mode="transcribe", **kw)
    except Exception as e:
        return fail(f"Transcription failed: {str(e)[:300]}")
    text = (getattr(r, "transcript", "") or "").strip()
    if not text:
        return fail("No speech was recognised in this audio.", 422)
    return {"transcript": text, "language_code": getattr(r, "language_code", None)}


class AnalyzeIn(BaseModel):
    transcript: str
    lang: str = "en"
    sample_id: str | None = None


PROMPT = """You are a careful fraud-awareness assistant for ordinary Indian users. Read the call transcript and judge it ONLY from what it contains.
Rules: never claim to know who the speaker is; never say a call is definitely fraud or definitely safe; a mention of a bank, money, an OTP or urgency is not proof by itself - weigh the whole context (e.g. a caller who warns you NOT to share an OTP is a good sign).
Every suspicious_phrases[].phrase must be copied EXACTLY, character for character, from the transcript. If nothing is suspicious, return an empty list.
Write explanation, reason, safe_next_steps, spoken_warning, uncertainty_note and short_summary in {lang}, in simple, warm everyday words (no jargon). spoken_warning is at most 4 short sentences.
Reply with ONLY one JSON object, no markdown, with keys:
risk_level ("High"|"Medium"|"Low"|"Uncertain"), short_summary, explanation, suspicious_phrases [{{"phrase","reason"}}], tactics [short strings], missing_evidence [strings], safe_next_steps [strings], spoken_warning, uncertainty_note."""

NORM = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()

SAMPLES = {
    "scam": "नमस्कार सर, मी बँकेतून बोलत आहे. तुमचे खाते आज बंद होणार आहे. ते सुरू ठेवण्यासाठी लगेच तुमचा OTP सांगा. नाहीतर तुमचे पैसे अडकतील.",
    "ambiguous": "नमस्कार, मी तुमच्या बँकेच्या शाखेतून बोलत आहे. तुमच्या कर्जाचा हप्ता उद्या देय आहे. कृपया बँकेच्या अधिकृत अॅपवरून भरा. आम्ही कधीही OTP किंवा पासवर्ड विचारत नाही.",
}
OFFLINE = {  # pre-written, clearly labelled as NOT live AI output; used only if the live call fails
    "scam": {"risk_level": "High", "short_summary": "कॉल करणारा बँकेचा असल्याचा दावा करतो, घाई करायला लावतो आणि OTP मागतो.",
             "explanation": "ही व्यक्ती बँकेतून बोलत असल्याचे सांगते, पण ते खरे आहे हे तपासलेले नाही. 'खाते आज बंद होणार' अशी भीती घालून तुम्हाला विचार करायला वेळ दिला जात नाही, आणि OTP मागितला जातो. OTP दिल्यास तुमच्या खात्यातून पैसे जाऊ शकतात. खरी बँक कधीही OTP विचारत नाही.",
             "suspicious_phrases": [{"phrase": "मी बँकेतून बोलत आहे", "reason": "बँकेचा दावा आहे, पण ओळख तपासलेली नाही."},
                                    {"phrase": "तुमचे खाते आज बंद होणार आहे", "reason": "भीती घालून घाई करायला लावणारी धमकी."},
                                    {"phrase": "लगेच तुमचा OTP सांगा", "reason": "OTP मागणे हे फसवणुकीचे सर्वात मोठे लक्षण आहे."},
                                    {"phrase": "नाहीतर तुमचे पैसे अडकतील", "reason": "नुकसानाची भीती दाखवून दबाव आणला जात आहे."}],
             "tactics": ["Impersonation", "Urgency", "OTP request", "Pressure"], "missing_evidence": ["कॉलरचा खरा नंबर", "बँकेकडून आलेला कोणताही अधिकृत संदेश"],
             "safe_next_steps": ["OTP कोणालाही सांगू नका.", "कॉल बंद करा.", "बँकेच्या अधिकृत नंबरवर (कार्डमागील / अधिकृत अॅप) स्वतः फोन करा.", "कॉलरने दिलेला नंबर वापरू नका."],
             "spoken_warning": "सावधान! या संभाषणात फसवणुकीची काही लक्षणे दिसत आहेत. समोरची व्यक्ती बँकेतून बोलत असल्याचा दावा करते आणि OTP मागते. तुमचा OTP कोणालाही सांगू नका. बँकेशी अधिकृत संपर्क माध्यमातूनच संपर्क साधा.",
             "uncertainty_note": "हे फक्त शब्दांवरून केलेले मूल्यमापन आहे; कॉल खरा की खोटा याची हमी देता येत नाही."},
    "ambiguous": {"risk_level": "Low", "short_summary": "हप्त्याची आठवण आहे आणि कॉलर OTP न मागता अधिकृत अॅप वापरायला सांगतो.",
                  "explanation": "इथे घाई, धमकी किंवा OTP ची मागणी दिसत नाही. उलट, कॉलर अधिकृत अॅपवरून भरायला सांगतो आणि OTP कधीच विचारत नाही असे सांगतो. तरीही कॉल करणारी व्यक्ती खरी बँक आहे हे तपासलेले नाही, म्हणून सावध रहा.",
                  "suspicious_phrases": [], "tactics": [], "missing_evidence": ["कॉलरची ओळख", "तुमचा हप्ता खरंच उद्या देय आहे का"],
                  "safe_next_steps": ["तुमच्या बँक अॅपमध्ये स्वतः हप्त्याची तारीख तपासा.", "कोणतीही लिंक किंवा नंबर कॉलरकडून घेऊ नका."],
                  "spoken_warning": "या संभाषणात फसवणुकीची स्पष्ट लक्षणे दिसत नाहीत. तरीही हप्त्याची तारीख तुमच्या बँक अॅपमध्ये स्वतः तपासा आणि कोणालाही OTP देऊ नका.",
                  "uncertainty_note": "ओळख तपासता येत नाही, म्हणून हे निश्चित नाही."},
}


def parse_json(raw: str):
    raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S)
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("model did not return JSON")
    return json.loads(raw[a:b + 1])


@app.post("/api/analyze")
def analyze(body: AnalyzeIn):
    t = body.transcript.strip()
    if not t:
        return fail("There is no transcript to analyse.", 422)
    name = LANGS.get(body.lang, LANGS["en"])[0]
    try:
        r = client().chat.completions(model=CHAT, messages=[
            {"role": "system", "content": PROMPT.format(lang=name)},
            {"role": "user", "content": f"Transcript:\n\"\"\"\n{t}\n\"\"\""}])
        res, source = parse_json(r.choices[0].message.content), "live"
    except Exception as e:
        sid = next((k for k, v in SAMPLES.items() if NORM(v) == NORM(t)), None)
        if sid and body.lang == "mr":
            res, source = dict(OFFLINE[sid]), "offline-demo"
        else:
            return fail(f"Analysis failed: {str(e)[:300]}")
    items = [p for p in res.get("suspicious_phrases", []) if isinstance(p, dict) and p.get("phrase")]
    kept = [p for p in items if NORM(p["phrase"]) in NORM(t)]  # drop anything not literally in the transcript
    res["suspicious_phrases"], res["dropped_unverified"], res["source"] = kept, len(items) - len(kept), source
    if res.get("risk_level") not in ("High", "Medium", "Low", "Uncertain"):
        res["risk_level"] = "Uncertain"
    return res


class TtsIn(BaseModel):
    text: str
    lang: str = "en"


@app.post("/api/tts")
def tts(body: TtsIn):
    text = body.text.strip()[:1400]
    if not text:
        return fail("Nothing to speak.", 422)
    kw = {"speaker": TTS_SPEAKER} if TTS_SPEAKER else {}
    try:
        r = client().text_to_speech.convert(text=text, language_code=LANGS.get(body.lang, LANGS["en"])[1], model=TTS, **kw)
    except Exception as e:
        return fail(f"Voice generation failed: {str(e)[:300]}")
    return {"audio_b64": "".join(r.audios), "mime": "audio/wav"}
