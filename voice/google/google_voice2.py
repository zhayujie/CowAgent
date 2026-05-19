import os
import time
import uuid
import json
from google.cloud import speech
from google.cloud import texttospeech_v1 as texttospeech
from google.cloud import storage
from google.api_core.exceptions import GoogleAPIError
from pydub import AudioSegment
from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from voice.voice import Voice
from common.utils import remove_markdown_symbol

# 设置 Google Cloud 凭据和配置文件路径
cred_path = os.path.join(os.path.dirname(__file__), "google-credentials.json")
config_path = os.path.join(os.path.dirname(__file__), "config.json")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path

class GoogleVoice(Voice):
    def __init__(self):
        super().__init__()
        self.speech_client = speech.SpeechClient()
        self.tts_client = texttospeech.TextToSpeechClient()
        self.tts_long_client = texttospeech.TextToSpeechLongAudioSynthesizeClient()
        self.storage_client = storage.Client()
        # 从 google-credentials.json 获取 project_id
        try:
            with open(cred_path, 'r') as f:
                credentials = json.load(f)
                self.project_id = credentials.get('project_id')
                if not self.project_id:
                    raise ValueError("project_id 未在 google-credentials.json 中找到")
                logger.debug(f"从 JSON 获取 project_id: {self.project_id}")
        except Exception as e:
            logger.error(f"无法读取 project_id: {e}")
            raise
        # 从 config.json 获取 bucket_name
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                self.bucket_name = config.get('gcs_bucket_name')
                if not self.bucket_name:
                    raise ValueError("gcs_bucket_name 未在 config.json 中找到")
                logger.debug(f"从 config.json 获取 bucket_name: {self.bucket_name}")
        except Exception as e:
            logger.error(f"无法读取 config.json: {e}")
            raise

    def convert_audio_to_wav(self, input_file_path, output_file_path="temp_audio.wav"):
        """
        将 AMR 或 MP3 文件转换为 WAV 格式
        参数:
            input_file_path: 输入音频文件路径（AMR 或 MP3）
            output_file_path: 输出 WAV 文件路径
        返回:
            转换后的 WAV 文件路径及其采样率
        """
        try:
            audio = AudioSegment.from_file(input_file_path)
            sample_rate = audio.frame_rate
            duration_ms = len(audio)
            logger.debug(f"输入音频: {input_file_path}, 采样率: {sample_rate}Hz, 时长: {duration_ms/1000}s")
            if duration_ms < 100:
                logger.error("音频文件过短，无法处理")
                return None, None
            audio = audio.set_channels(1).set_sample_width(2)
            audio.export(output_file_path, format="wav", codec="pcm_s16le")
            return output_file_path, sample_rate
        except Exception as e:
            logger.error(f"音频转换失败: {e}")
            return None, None

    def voiceToText(self, voice_file):
        """
        将中文音频文件（AMR 或 MP3）转换为文本
        参数:
            voice_file: 输入音频文件路径
        返回:
            Reply 对象，包含转录文本或错误信息
        """
        try:
            if not os.path.exists(voice_file) or os.path.getsize(voice_file) == 0:
                logger.error(f"音频文件无效或为空: {voice_file}")
                return Reply(ReplyType.ERROR, "音频文件无效或为空")

            file_ext = os.path.splitext(voice_file)[1].lower()
            if file_ext in [".amr", ".mp3"]:
                temp_wav_file = f"temp_audio_{uuid.uuid4().hex}.wav"
                voice_file, sample_rate = self.convert_audio_to_wav(voice_file, temp_wav_file)
                if not voice_file:
                    logger.error("音频转换失败")
                    return Reply(ReplyType.ERROR, "音频转换失败")
            elif file_ext == ".wav":
                audio = AudioSegment.from_wav(voice_file)
                sample_rate = audio.frame_rate
                duration_ms = len(audio)
                logger.debug(f"WAV 音频: {voice_file}, 采样率: {sample_rate}Hz, 时长: {duration_ms/1000}s")
                if duration_ms < 100:
                    logger.error("音频文件过短，无法处理")
                    return Reply(ReplyType.ERROR, "音频文件过短，无法处理")
            else:
                logger.error("不支持的音频格式，仅支持 AMR、MP3 和 WAV")
                return Reply(ReplyType.ERROR, "不支持的音频格式，仅支持 AMR、MP3 和 WAV")

            with open(voice_file, "rb") as audio_file:
                audio_content = audio_file.read()

            audio = speech.RecognitionAudio(content=audio_content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=sample_rate,
                language_code="cmn-CN",
            )

            response = self.speech_client.recognize(config=config, audio=audio)

            transcript = ""
            for result in response.results:
                transcript += result.alternatives[0].transcript + " "

            transcript = transcript.strip()
            if not transcript:
                logger.error("语音识别失败：无法理解音频内容")
                return Reply(ReplyType.ERROR, "抱歉，我听不懂")

            logger.info(f"[Google] voiceToText text={transcript} voice file name={voice_file}")
            reply = Reply(ReplyType.TEXT, transcript)

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
            text: 要转换的中文文本（可能包含 Markdown 标记）
        返回:
            Reply 对象，包含音频文件路径或错误信息
        """
        try:
            # 清理 Markdown 标记
            cleaned_text = remove_markdown_symbol(text)
            if not cleaned_text:
                logger.error("清理后的文本为空")
                return Reply(ReplyType.ERROR, "文本内容为空，无法转换")

            # 检查文本字节长度
            text_bytes = cleaned_text.encode('utf-8')
            byte_length = len(text_bytes)
            logger.debug(f"文本字节长度: {byte_length} 字节")

            # 生成唯一的输出文件名
            unique_id = uuid.uuid4().hex
            mp3_file = f"{TmpDir().path()}reply-{int(time.time())}-{unique_id}.mp3"
            gcs_output_path = f"output-{unique_id}.wav"  # Long Audio 使用 WAV

            # 配置语音参数（中文普通话）
            voice = texttospeech.VoiceSelectionParams(
                language_code="cmn-CN",
                name="cmn-CN-Wavenet-A",
            )

            if byte_length <= 5000:
                # 使用标准 Text-to-Speech API（短文本，输出 MP3）
                audio_config = texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.MP3
                )
                synthesis_input = texttospeech.SynthesisInput(text=cleaned_text)
                response = self.tts_client.synthesize_speech(
                    input=synthesis_input, voice=voice, audio_config=audio_config
                )
                with open(mp3_file, "wb") as out:
                    out.write(response.audio_content)
                    logger.info(f"[Google] textToVoice (standard) text={cleaned_text[:50]}... voice file name={mp3_file}")
                return Reply(ReplyType.VOICE, mp3_file)
            else:
                # 使用 Long Audio API（长文本，输出 LINEAR16/WAV）
                audio_config = texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.LINEAR16
                )
                parent = f"projects/{self.project_id}/locations/global"
                synthesis_input = texttospeech.SynthesisInput(text=cleaned_text)
                output_gcs_uri = f"gs://{self.bucket_name}/{gcs_output_path}"
                request = texttospeech.SynthesizeLongAudioRequest(
                    parent=parent,
                    input=synthesis_input,
                    audio_config=audio_config,
                    voice=voice,
                    output_gcs_uri=output_gcs_uri,
                )
                operation = self.tts_long_client.synthesize_long_audio(request=request)
                result = operation.result(timeout=600)  # 等待长音频合成完成（最大 10 分钟）

                # 从 GCS 下载 WAV 文件
                temp_wav_file = f"{TmpDir().path()}temp_wav_{unique_id}.wav"
                bucket = self.storage_client.bucket(self.bucket_name)
                blob = bucket.blob(gcs_output_path)
                blob.download_to_filename(temp_wav_file)
                logger.debug(f"从 GCS 下载 WAV 文件: {temp_wav_file}")

                # 转换为 MP3
                audio = AudioSegment.from_wav(temp_wav_file)
                audio.export(mp3_file, format="mp3")
                logger.info(f"[Google] textToVoice (long audio) text={cleaned_text[:50]}... voice file name={mp3_file}")

                # 清理临时文件
                os.remove(temp_wav_file)
                blob.delete()

                return Reply(ReplyType.VOICE, mp3_file)

        except GoogleAPIError as e:
            logger.error(f"文字转语音失败: {e}")
            return Reply(ReplyType.ERROR, f"抱歉，无法连接到 Google 文字转语音服务；{e}")
        except Exception as e:
            logger.error(f"发生错误: {e}")
            return Reply(ReplyType.ERROR, f"发生错误：{e}")

"""
语言代码: yue-HK
  名称: yue-HK-Standard-A, 性别: FEMALE, 采样率: 24000Hz
  名称: yue-HK-Standard-B, 性别: MALE, 采样率: 24000Hz
  名称: yue-HK-Standard-C, 性别: FEMALE, 采样率: 24000Hz
  名称: yue-HK-Standard-D, 性别: MALE, 采样率: 24000Hz

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

语言代码: cmn-TW
  名称: cmn-TW-Standard-A, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-TW-Standard-B, 性别: MALE, 采样率: 24000Hz
  名称: cmn-TW-Standard-C, 性别: MALE, 采样率: 24000Hz
  名称: cmn-TW-Wavenet-A, 性别: FEMALE, 采样率: 24000Hz
  名称: cmn-TW-Wavenet-B, 性别: MALE, 采样率: 24000Hz
  名称: cmn-TW-Wavenet-C, 性别: MALE, 采样率: 24000Hz
"""