import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import requests
import json
from datetime import datetime, timedelta
from xhapi.my_ops.common.readconfig import ini

# Cookie缓存配置
COOKIE_CACHE = {}  # 格式: {env: {'cookie_string': str, 'expire_time': datetime}}
CACHE_DURATION = 10  # 缓存时长（分钟）

# RSA公钥
PUBLIC_KEY=ini.ops_public_key
def encrypt(txt):
    """
    使用RSA公钥加密文本
    :param txt: 需要加密的文本
    :return: base64编码的加密结果
    """
    # 将base64编码的公钥转换为PEM格式
    public_key_der = base64.b64decode(PUBLIC_KEY)
    # 加载公钥
    public_key = serialization.load_der_public_key(
        public_key_der,
        backend=default_backend()
    )
    # 使用PKCS1v15填充方式加密
    encrypted = public_key.encrypt(
        txt.encode('utf-8'),
        padding.PKCS1v15()
    )
    # 返回base64编码的加密结果
    return base64.b64encode(encrypted).decode('utf-8')

def login(env,appid):
    cookie_id=f"{env}_{appid}"
    # 检查该环境的缓存是否有效
    if cookie_id in COOKIE_CACHE:
        cache = COOKIE_CACHE[cookie_id]
        if cache['cookie_string'] and cache['expire_time']:
            if datetime.now() < cache['expire_time']:
                print(f"使用缓存的cookie（环境: {env},appid:{appid},剩余有效时间: {(cache['expire_time'] - datetime.now()).seconds}秒）")
                return cache['cookie_string']
            else:
                print(f"缓存已过期（环境: {env},appid:{appid}），重新登录...")
    else:
        print(f"首次登录环境: {env},appid:{appid}")

    url = f"https://sso.xhqb.xyz/sso-api/login"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    server = {
        "bossmgr": "https%3A%2F%2Ftest3.xiaohuaai.com%2Fboss-mgr-api%2FpreLogin%3ForiginUrl%3Dhttps%253A%252F%252Ftest3.xiaohuaai.com%252Fbossmgr%252F%2523%252Fadv%252FBGALL",
        "droolsCms": "https%3A%2F%2Ftest3.xiaohuaai.com%2Fdrools-cms%2FpreLogin%3ForiginUrl%3Dhttps%253A%252F%252Ftest3.xiaohuaai.com%252Fstrategy-admin%252Fhome"
    }
    data = {}
    data["username"] = ini.sso_username
    data["password"] = encrypt(ini.sso_password)
    data['appId']=appid
    data['userType']='local'
    data['redirectUri']=server.get(appid).replace("test3",env)

    # 创建session以保持cookies
    session = requests.Session()
    response = session.post(url, data=data, headers=headers, allow_redirects=True)
    cookies = session.cookies.get_dict()
    cookie_string = "; ".join([f"{name}={value}" for name, value in cookies.items()])

    # 更新该环境的缓存
    COOKIE_CACHE[cookie_id] = {
        'cookie_string': cookie_string,
        'expire_time': datetime.now() + timedelta(minutes=CACHE_DURATION)
    }
    return cookie_string
