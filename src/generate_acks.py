"""
One-time script to pre-generate acknowledgment audio files for all 7 languages.

Run once:
    python src/generate_acks.py

Generates WAV files in src/meera_acks/<lang>/
using Meera DragonHD voice with correct xml:lang per language.
Commit the generated .wav files to the repo.
"""

import os
import sys
import azure.cognitiveservices.speech as speechsdk
from xml.sax import saxutils
from pathlib import Path
from dotenv import load_dotenv
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()
AZURE_SPEECH_KEY    = "E7mHLG7UxtcWNew7wQlBrfg6F7I2Kjsxek5dsAaXL9qpxpUPilANJQQJ99CFACGhslBXJ3w3AAAYACOGAJEp"
AZURE_SPEECH_REGION = "centralindia"

VOICE       = "en-IN-Meera:DragonHDLatestNeural"
SAMPLE_RATE = 8000
BITS        = 16
CHANNELS    = 1

# Natural acknowledgment phrases per language
# Format: { lang_folder: (xml_lang, [ (filename, text), ... ]) }
ACK_FILES = {
    "hi": ("hi-IN", [
        ("ek_moment.wav",     "एक moment दीजिये।"),
        ("ji_zaroor.wav",     "जी ज़रूर।"),
        ("theek_hai.wav",     "ठीक है।"),
        ("bilkul_ji.wav",     "बिल्कुल जी।"),
        ("ji_ek_second.wav",  "जी, एक second।"),
    ]),
    "en": ("en-IN", [
        ("hmm_just_a_second.wav",  "Hmmm, just a second."),
        ("okay_i_understand.wav",  "Okay, I understand."),
        ("sure_one_moment.wav",    "Sure, one moment."),
        ("understood.wav",         "Understood."),
        ("right_away.wav",         "Right away."),
    ]),
}


def synthesize_to_wav(text: str, xml_lang: str, output_path: Path):
    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY,
        region=AZURE_SPEECH_REGION
    )
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff8Khz16BitMonoPcm
    )

    ssml = (
        f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{xml_lang}'>"
        f"<voice name='{VOICE}'>"
        f"<prosody rate='0.95' pitch='+0%'>{saxutils.escape(text)}</prosody>"
        f"</voice></speak>"
    )

    synth = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synth.speak_ssml_async(ssml).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        with open(str(output_path), 'wb') as f:
            f.write(result.audio_data)
        print(f"  ✅ {output_path.name} ({len(result.audio_data):,} bytes) — '{text}'")
    else:
        details = result.cancellation_details
        print(f"  ❌ {output_path.name}: {details.error_details}")


def main():
    base = Path(__file__).parent / "meera_acks"

    for lang_folder, (xml_lang, entries) in ACK_FILES.items():
        lang_dir = base / lang_folder
        lang_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n[{lang_folder} / {xml_lang}] Generating {len(entries)} acks...")

        for filename, text in entries:
            output_path = lang_dir / filename
            synthesize_to_wav(text, xml_lang, output_path)

    print("\n✅ All ack files generated in src/meera_acks/")


if __name__ == "__main__":
    main()
