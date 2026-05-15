import os
import time
import uuid
from google.cloud import speech
from google.cloud import texttospeech
from google.api_core.exceptions import GoogleAPIError
from pydub import AudioSegment
from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from voice.voice import Voice

# 设置 Google Cloud 凭据
cred_path = os.path.join(os.path.dirname(__file__), "google-credentials.json")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path

class GoogleVoice(Voice):
    def __init__(self):
        super().__init__() 
        self.speech_client = speech.SpeechClient()
        self.tts_client = texttospeech.TextToSpeechClient()

    def convert_audio_to_wav(self, input_file_path, output_file_path="temp_audio.wav"):
        """
        将 AMR 或 MP3 文件转换为 WAV 格式
        参数:
            input_file_path: 输入音频文件路径（AMR 或 MP3）
            output_file_path: 输出 WAV 文件路径
        返回:
            转换后的 WAV 文件路径
        """
        try:
            audio = AudioSegment.from_file(input_file_path)
            audio = audio.set_frame_rate(16000).set_channels(1)
            audio.export(output_file_path, format="wav")
            return output_file_path
        except Exception as e:
            logger.error(f"音频转换失败: {e}")
            return None

    def voiceToText(self, voice_file):
        """
        将中文音频文件（AMR 或 MP3）转换为文本
        参数:
            voice_file: 输入音频文件路径
        返回:
            Reply 对象，包含转录文本或错误信息
        """
        try:
            file_ext = os.path.splitext(voice_file)[1].lower()
            if file_ext in [".amr", ".mp3"]:
                temp_wav_file = f"temp_audio_{uuid.uuid4().hex}.wav" 
                voice_file = self.convert_audio_to_wav(voice_file, temp_wav_file)
                if not voice_file:
                    logger.error("音频转换失败")
                    return Reply(ReplyType.ERROR, "音频转换失败")
            elif file_ext != ".wav":
                logger.error("不支持的音频格式，仅支持 AMR、MP3 和 WAV")
                return Reply(ReplyType.ERROR, "不支持的音频格式，仅支持 AMR、MP3 和 WAV")

            with open(voice_file, "rb") as audio_file:
                audio_content = audio_file.read()

            # 配置音频和识别设置（中文普通话）
            audio = speech.RecognitionAudio(content=audio_content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code="cmn-CN", 
            )

            # 执行语音识别
            response = self.speech_client.recognize(config=config, audio=audio)

            # 提取转录结果
            transcript = ""
            for result in response.results:
                transcript += result.alternatives[0].transcript + " "

            transcript = transcript.strip()
            if not transcript:
                logger.error("语音识别失败：无法理解音频内容")
                return Reply(ReplyType.ERROR, "抱歉，我听不懂")

            logger.info(f"[Google] voiceToText text={transcript} voice file name={voice_file}")
            reply = Reply(ReplyType.TEXT, transcript)

            # 清理临时 WAV 文件
            if file_ext in [".amr", ".mp3"] and os.path.exists(voice_file):
                os.remove(voice_file)

            return reply

        except GoogleAPIError as e:
            logger.error(f"语音识别失败：无法连接到 Google 语音识别服务；{e}")
            return Reply(ReplyType.ERROR, f"抱歉，无法连接到 Google 语音识别服务；{e}")
        except Exception as e:
            logger.error(f"发生错误: {e}")
            return Reply(ReplyType.ERROR, f"抱歉，我听不懂或发生错误：{e}")

    def textToVoice(self, text):
        """
        将中文文本转换为语音并保存为音频文件
        参数:
            text: 要转换的中文文本
        返回:
            Reply 对象，包含音频文件路径或错误信息
        """
        try:
            # 生成唯一的输出文件名
            unique_id = uuid.uuid4().hex
            mp3_file = f"{TmpDir().path()}reply-{int(time.time())}-{unique_id}.mp3"

            # 配置要转换的文本
            synthesis_input = texttospeech.SynthesisInput(text=text)

            # 配置语音参数（中文普通话）
            voice = texttospeech.VoiceSelectionParams(
                language_code="cmn-CN",
                name="cmn-CN-Wavenet-A",
            )

            # 配置音频输出格式
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )

            # 执行文字转语音
            response = self.tts_client.synthesize_speech(
                input=synthesis_input, voice=voice, audio_config=audio_config
            )

            # 保存音频文件
            with open(mp3_file, "wb") as out:
                out.write(response.audio_content)
                logger.info(f"[Google] textToVoice text={text} voice file name={mp3_file}")

            return Reply(ReplyType.VOICE, mp3_file)

        except GoogleAPIError as e:
            logger.error(f"文字转语音失败: {e}")
            return Reply(ReplyType.ERROR, f"抱歉，无法连接到 Google 文字转语音服务；{e}")
        except Exception as e:
            logger.error(f"发生错误: {e}")
            return Reply(ReplyType.ERROR, f"发生错误：{e}")
        

"""
语言代码: cmn-CN
  名称: cmn-CN-Chirp3-HD-Achernar, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Achird, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Algenib, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Algieba, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Alnilam, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Aoede, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Autonoe, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Callirrhoe, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Charon, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Despina, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Enceladus, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Erinome, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Fenrir, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Gacrux, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Iapetus, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Kore, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Laomedeia, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Leda, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Orus, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Puck, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Pulcherrima, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Rasalgethi, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Sadachbia, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Sadaltager, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Schedar, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Sulafat, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Umbriel, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Vindemiatrix, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Zephyr, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Chirp3-HD-Zubenelgenubi, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Standard-A, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Standard-B, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Standard-C, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Standard-D, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Wavenet-A, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-CN-Wavenet-B, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Wavenet-C, 性别: MALE, 采样率: 24000Hz
  名称: cmn-CN-Wavenet-D, 性别: FEMALE, 采样率: 24000Hz
"""

