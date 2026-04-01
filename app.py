from flask import Flask, request, redirect, jsonify
from utils import get_next_id, encode, save_mapping, get_long_url, init_bloom_filter

app = Flask(__name__)

# 应用启动时初始化布隆过滤器
init_bloom_filter()

@app.route('/shorten', methods=['POST'])
def shorten():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "Missing url"}), 400
    long_url = data['url']

    next_id = get_next_id()
    short_code = encode(next_id)

    save_mapping(short_code, long_url)

    short_url = f"http://localhost:5000/{short_code}"
    return jsonify({"short_url": short_url, "code": short_code})

@app.route('/<short_code>')
def redirect_to_url(short_code):
    long_url = get_long_url(short_code)
    if long_url:
        return redirect(long_url)
    else:
        return jsonify({"error": "Short code not found"}), 404

if __name__ == '__main__':
    app.run(debug=True)