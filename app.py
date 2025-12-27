from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import os
import threading
import time

app = Flask(__name__)
CORS(app)

# ----------------------------------------------------------
# 1. FORCE JSON FILES INTO "frontend"
# ----------------------------------------------------------
BASE_DIR = Path(__file__).parent
FRONTEND_DIR = BASE_DIR / 'frontend'
FRONTEND_DIR.mkdir(exist_ok=True)

WHISPERS_FILE = FRONTEND_DIR / 'whispers.json'
REPLIES_FILE = FRONTEND_DIR / 'replies.json'

# Global variable to track last update time - FIXED datetime warning
LAST_UPDATE_TIME = datetime.now(timezone.utc)

# ----------------------------------------------------------
# 2. CREATE EMPTY JSON FILES IF THEY DON'T EXIST
# ----------------------------------------------------------
def init_data():
    if not WHISPERS_FILE.exists():
        WHISPERS_FILE.write_text('[]')
    if not REPLIES_FILE.exists():
        REPLIES_FILE.write_text('[]')

init_data()

# ----------------------------------------------------------
# 3. UTILS
# ----------------------------------------------------------
ALL_TOPICS = [
    'confession', 'life', 'secrets', 'advice', 'love',
    'series-movies', 'politically-incorrect', 'paranormal',
    'health-fitness', 'vent', 'music', 'fashion',
    'gaming', 'otaku-stuff', 'random'
]

def load_data(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'load_data error: {e}')
        return []

def save_data(file_path, data):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        global LAST_UPDATE_TIME
        LAST_UPDATE_TIME = datetime.now(timezone.utc)  # Update timestamp - FIXED
        return True
    except Exception as e:
        print(f'save_data error: {e}')
        return False

def cleanup_old_whispers():
    try:
        whispers = load_data(WHISPERS_FILE)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=48)  # FIXED
        filtered_whispers, deleted_ids = [], []

        for w in whispers:
            if datetime.fromisoformat(w['created_at'].replace('Z', '+00:00')) > cutoff_time:
                filtered_whispers.append(w)
            else:
                deleted_ids.append(w['id'])

        if deleted_ids:
            replies = load_data(REPLIES_FILE)
            filtered_replies = [r for r in replies if r['whisper_id'] not in deleted_ids]
            save_data(REPLIES_FILE, filtered_replies)
            save_data(WHISPERS_FILE, filtered_whispers)
        return True
    except Exception as e:
        print(f'cleanup error: {e}')
        return False

# Auto-cleanup thread
def auto_cleanup():
    while True:
        time.sleep(60)  # Cleanup every minute
        cleanup_old_whispers()

# Start cleanup thread
cleanup_thread = threading.Thread(target=auto_cleanup, daemon=True)
cleanup_thread.start()

# ----------------------------------------------------------
# 4. STATIC FRONT-END ROUTES - SIMPLIFIED
# ----------------------------------------------------------
@app.route('/')
def serve_index():
    return send_from_directory(FRONTEND_DIR, 'index.html')

@app.route('/<path:path>')
def serve_static_files(path):
    if path == '':
        path = 'index.html'
    return send_from_directory(FRONTEND_DIR, path)

# ----------------------------------------------------------
# 5. API ROUTES WITH AUTO-RELOAD SUPPORT
# ----------------------------------------------------------
@app.route('/api/whispers', methods=['GET'])
def get_whispers():
    try:
        cleanup_old_whispers()
        topic = request.args.get('topic', 'all')
        whispers = load_data(WHISPERS_FILE)
        
        # FIXED: Proper topic filtering
        if topic and topic != 'all':
            # Ensure topic is valid
            if topic not in ALL_TOPICS:
                topic = 'all'
            
            # Filter whispers by topic - FIXED
            filtered_whispers = []
            for w in whispers:
                # Ensure whisper has topic field, default to 'random' if missing
                whisper_topic = w.get('topic', 'random')
                if whisper_topic == topic:
                    filtered_whispers.append(w)
            
            whispers = filtered_whispers
        
        whispers.sort(key=lambda x: x['created_at'], reverse=True)
        
        # Return last update time for frontend to detect changes
        return jsonify({
            'success': True, 
            'data': whispers,
            'last_update': LAST_UPDATE_TIME.isoformat(),
            'current_topic': topic  # Send back the topic we filtered by
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/check-updates', methods=['GET'])
def check_updates():
    """Endpoint for frontend to check if data has changed"""
    last_client_update = request.args.get('last_update')
    client_topic = request.args.get('topic', 'all')  # Get current topic from client
    
    try:
        # Get current whispers to see if anything changed
        whispers = load_data(WHISPERS_FILE)
        
        # Apply topic filtering for checking updates too
        if client_topic and client_topic != 'all':
            if client_topic not in ALL_TOPICS:
                client_topic = 'all'
            else:
                # Filter whispers by topic
                filtered_whispers = []
                for w in whispers:
                    whisper_topic = w.get('topic', 'random')
                    if whisper_topic == client_topic:
                        filtered_whispers.append(w)
                current_count = len(filtered_whispers)
        else:
            current_count = len(whispers)
        
        # Check if data has changed since client's last update
        if last_client_update:
            try:
                client_time = datetime.fromisoformat(last_client_update.replace('Z', '+00:00'))
                data_changed = LAST_UPDATE_TIME > client_time
            except:
                data_changed = True
        else:
            data_changed = True
            
        return jsonify({
            'success': True,
            'has_updates': data_changed,
            'last_update': LAST_UPDATE_TIME.isoformat(),
            'total_whispers': current_count,
            'topic': client_topic
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/whispers/<int:id>', methods=['GET'])
def get_whisper(id):
    whispers = load_data(WHISPERS_FILE)
    whisper = next((w for w in whispers if w['id'] == id), None)
    if not whisper:
        return jsonify({'success': False, 'error': 'Whisper not found'}), 404
    
    # Get replies count
    replies = load_data(REPLIES_FILE)
    whisper['replies_count'] = len([r for r in replies if r['whisper_id'] == id])
    
    return jsonify({'success': True, 'data': whisper})

@app.route('/api/whispers', methods=['POST'])
def create_whisper():
    data = request.get_json()
    if not data or not data.get('content'):
        return jsonify({'success': False, 'error': 'Content required'}), 400

    whispers = load_data(WHISPERS_FILE)
    new_id = max([w['id'] for w in whispers], default=0) + 1
    
    # Validate topic
    topic = data.get('topic', 'random')
    if topic not in ALL_TOPICS:
        topic = 'random'
    
    whisper = {
        'id': new_id,
        'content': data['content'].strip(),
        'topic': topic,
        'is_sensitive': data.get('is_sensitive', False),
        'replies_count': 0,
        'created_at': datetime.now(timezone.utc).isoformat()  # FIXED
    }
    
    whispers.append(whisper)
    if save_data(WHISPERS_FILE, whispers):
        return jsonify({'success': True, 'data': whisper})
    return jsonify({'success': False, 'error': 'Save failed'}), 500

@app.route('/api/whispers/<int:id>/replies', methods=['GET'])
def get_replies(id):
    replies = load_data(REPLIES_FILE)
    replies = [r for r in replies if r['whisper_id'] == id]
    replies.sort(key=lambda x: x['created_at'])
    return jsonify({'success': True, 'data': replies})

@app.route('/api/whispers/<int:id>/replies', methods=['POST'])
def create_reply(id):
    data = request.get_json()
    if not data or not data.get('content'):
        return jsonify({'success': False, 'error': 'Content required'}), 400

    whispers = load_data(WHISPERS_FILE)
    whisper = next((w for w in whispers if w['id'] == id), None)
    if not whisper:
        return jsonify({'success': False, 'error': 'Whisper not found'}), 404

    replies = load_data(REPLIES_FILE)
    new_id = max([r['id'] for r in replies], default=0) + 1
    reply = {
        'id': new_id,
        'whisper_id': id,
        'content': data['content'].strip(),
        'created_at': datetime.now(timezone.utc).isoformat()  # FIXED
    }
    
    replies.append(reply)
    if save_data(REPLIES_FILE, replies):
        # Update replies count in whisper
        whisper['replies_count'] = len([r for r in replies if r['whisper_id'] == id])
        save_data(WHISPERS_FILE, whispers)
        return jsonify({'success': True, 'data': reply})
    return jsonify({'success': False, 'error': 'Save failed'}), 500

@app.route('/api/topics', methods=['GET'])
def get_topics():
    return jsonify({'success': True, 'data': ALL_TOPICS})

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy'})

# ----------------------------------------------------------
# 6. RUN
# ----------------------------------------------------------
if __name__ == '__main__':
    print(f'Serving frontend from: {FRONTEND_DIR}')
    print(f'Whispers JSON location: {WHISPERS_FILE}')
    print(f'Replies JSON location: {REPLIES_FILE}')
    app.run(debug=True, port=5000, threaded=True)