import redis
import pymysql
import os
from pybloom_live import BloomFilter

# Redis 连接
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

# MySQL 连接配置
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'database': 'shortlink',
    'charset': 'utf8mb4'
}

# Base62 字符集
CHARSET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(CHARSET)

# 布隆过滤器持久化文件名
BLOOM_FILE = "bloom.dat"
bloom = None

def init_bloom_filter():
    """初始化布隆过滤器：优先从文件加载，否则从 MySQL 重建"""
    global bloom
    if os.path.exists(BLOOM_FILE):
        with open(BLOOM_FILE, 'rb') as f:
            bloom = BloomFilter.fromfile(f)
        print(f"从文件 {BLOOM_FILE} 加载布隆过滤器")
    else:
        # 从 MySQL 加载所有已有短码重建布隆过滤器
        # 容量设大一点，避免误判率升高（例如100万，误判率0.001）
        bloom = BloomFilter(capacity=1000000, error_rate=0.001)
        conn = pymysql.connect(**DB_CONFIG)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT short_code FROM shortlinks")
                for row in cursor.fetchall():
                    bloom.add(row[0])
        finally:
            conn.close()
        # 保存到文件
        with open(BLOOM_FILE, 'wb') as f:
            bloom.tofile(f)
        print(f"从 MySQL 重建布隆过滤器，并保存到 {BLOOM_FILE}")

def save_bloom_to_file():
    """将当前布隆过滤器写入文件"""
    with open(BLOOM_FILE, 'wb') as f:
        bloom.tofile(f)

def encode(num: int) -> str:
    """将整数转换为 Base62 字符串"""
    if num == 0:
        return CHARSET[0]
    result = []
    while num > 0:
        num, rem = divmod(num, BASE)
        result.append(CHARSET[rem])
    return ''.join(reversed(result))

def get_next_id() -> int:
    """使用 Redis INCR 生成全局唯一自增 ID"""
    return r.incr("shortlink:next_id")

def save_mapping(short_code: str, long_url: str):
    """将短码与长链接存入 Redis、MySQL，并添加到布隆过滤器"""
    # 存入 Redis（设置7天过期）
    r.setex(f"shortlink:{short_code}", 7 * 24 * 3600, long_url)

    # 存入 MySQL
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            sql = "INSERT INTO shortlinks (short_code, long_url) VALUES (%s, %s)"
            cursor.execute(sql, (short_code, long_url))
        conn.commit()
    finally:
        conn.close()

    # 添加到布隆过滤器
    bloom.add(short_code)
    # 持久化到文件（可考虑异步写入，这里简单同步）
    save_bloom_to_file()

def get_long_url(short_code: str) -> str:
    """先查布隆过滤器，再查 Redis，最后查 MySQL，并回写缓存"""
    # 1. 布隆过滤器检查：如果不存在，直接返回 None
    if short_code not in bloom:
        print(f"布隆过滤器拦截: {short_code}") 
        return None
    
    print(f"布隆过滤器通过: {short_code}，准备查 Redis/MySQL") 

    # 2. 查 Redis
    long_url = r.get(f"shortlink:{short_code}")
    if long_url:
        return long_url

    # 3. 查 MySQL
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            sql = "SELECT long_url FROM shortlinks WHERE short_code = %s"
            cursor.execute(sql, (short_code,))
            result = cursor.fetchone()
            if result:
                long_url = result[0]
                # 回写 Redis（并设置过期时间）
                r.setex(f"shortlink:{short_code}", 7 * 24 * 3600, long_url)
                return long_url
    finally:
        conn.close()

    return None