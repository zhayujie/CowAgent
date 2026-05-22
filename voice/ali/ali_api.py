# coding=utf-8
"""
Author: chazzjimel
Email: chazzjimel@gmail.com
wechat：cheung-z-x

Description:

"""

import http.client
import json
import time
import requests
import datetime
import hashlib
import hmac
import base64
import urllib.parse
import uuid

from common.log import logger
from common.tmp_dir import TmpDir


def text_to_speech_aliyun(url, text, appkey, token):
    """
    使用阿里云的文本转语音服务将文本转换为语音。

    参数:
    - url (str): 阿里云文本转语音服务的端点URL。
    - text (str): 要转换为语音的文本。
    - appkey (str): 您的阿里云appkey。
    - token (str): 阿里云API的认证令牌。

    返回值:
    - str: 成功时输出音频文件的路径，否则为None。
    """
    headers = {
        "Content-Type": "application/json",
    }

    data = {
        "text": text,
        "appkey": appkey,
        "token": token,
        "format": "wav"
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))

    if response.status_code == 200 and response.headers['Content-Type'] == 'audio/mpeg':
        output_file = TmpDir().path() + "reply-" + str(int(time.time())) + "-" + str(hash(text) & 0x7FFFFFFF) + ".wav"

        with open(output_file, 'wb') as file:
            file.write(response.content)
        logger.debug(f"音频文件保存成功，文件名：{output_file}")
    else:
        logger.debug("响应状态码: {}".format(response.status_code))
        logger.debug("响应内容: {}".format(response.text))
        output_file = None

    return output_file

def speech_to_text_aliyun(url, audioContent, appkey, token):
    """
    使用阿里云的语音识别服务识别音频文件中的语音。

    参数:
    - url (str): 阿里云语音识别服务的端点URL。
    - audioContent (byte): pcm音频数据。
    - appkey (str): 您的阿里云appkey。
    - token (str): 阿里云API的认证令牌。

    返回值:
    - str: 成功时输出识别到的文本，否则为None。
    """
    format = 'pcm'
    sample_rate = 16000
    enablePunctuationPrediction  = True
    enableInverseTextNormalization = True
    enableVoiceDetection  = False

    # 设置RESTful请求参数
    request = url + '?appkey=' + appkey
    request = request + '&format=' + format
    request = request + '&sample_rate=' + str(sample_rate)

    if enablePunctuationPrediction :
        request = request + '&enable_punctuation_prediction=' + 'true'

    if enableInverseTextNormalization :
        request = request + '&enable_inverse_text_normalization=' + 'true'

    if enableVoiceDetection :
        request = request + '&enable_voice_detection=' + 'true'
        
    host = 'nls-gateway-cn-shanghai.aliyuncs.com'

    # 设置HTTPS请求头部
    httpHeaders = {
        'X-NLS-Token': token,
        'Content-type': 'application/octet-stream',
        'Content-Length': len(audioContent)
        }

    conn = http.client.HTTPSConnection(host)
    conn.request(method='POST', url=request, body=audioContent, headers=httpHeaders)

    response = conn.getresponse()
    body = response.read()
    try:
        body = json.loads(body)
        status = body['status']
        if status == 20000000 :
            result = body['result']
            if result :
                logger.info(f"阿里云语音识别到了：{result}")
            conn.close()
            return result
        else :
            logger.error(f"语音识别失败，状态码: {status}")
    except ValueError:
        logger.error(f"语音识别失败，收到非JSON格式的数据: {body}")
    conn.close()
    return None


class AliyunTokenGenerator:
    """
    用于生成阿里云服务认证令牌的类。

    属性:
    - access_key_id (str): 您的阿里云访问密钥ID。
    - access_key_secret (str): 您的阿里云访问密钥秘密。
    """

    def __init__(self, access_key_id, access_key_secret):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret

    def sign_request(self, parameters):
        """
        为阿里云服务签名请求。

        参数:
        - parameters (dict): 请求的参数字典。

        返回值:
        - str: 请求的签名签章。
        """
        # 将参数按照字典顺序排序
        sorted_params = sorted(parameters.items())

        # 构造待签名的查询字符串
        canonicalized_query_string = ''
        for (k, v) in sorted_params:
            canonicalized_query_string += '&' + self.percent_encode(k) + '=' + self.percent_encode(v)

        # 构造用于签名的字符串
        string_to_sign = 'GET&%2F&' + self.percent_encode(canonicalized_query_string[1:])  # 使用GET方法

        # 使用HMAC算法计算签名
        h = hmac.new((self.access_key_secret + "&").encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha1)
        signature = base64.encodebytes(h.digest()).strip()

        return signature

    def percent_encode(self, encode_str):
        """
        对字符串进行百分比编码。

        参数:
        - encode_str (str): 要编码的字符串。

        返回值:
        - str: 编码后的字符串。
        """
        encode_str = str(encode_str)
        res = urllib.parse.quote(encode_str, '')
        res = res.replace('+', '%20')
        res = res.replace('*', '%2A')
        res = res.replace('%7E', '~')
        return res

    def get_token(self):
        """
        获取阿里云服务的令牌。

        返回值:
        - str: 获取到的令牌。
        """
        # 设置请求参数
        params = {
            'Format': 'JSON',
            'Version': '2019-02-28',
            'AccessKeyId': self.access_key_id,
            'SignatureMethod': 'HMAC-SHA1',
            'Timestamp': datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            'SignatureVersion': '1.0',
            'SignatureNonce': str(uuid.uuid4()),  # 使用uuid生成唯一的随机数
            'Action': 'CreateToken',
            'RegionId': 'cn-shanghai'
        }

        # 计算签名
        signature = self.sign_request(params)
        params['Signature'] = signature

        # 构造请求URL
        url = 'http://nls-meta.cn-shanghai.aliyuncs.com/?' + urllib.parse.urlencode(params)

        # 发送请求
        response = requests.get(url)

        return response.text
