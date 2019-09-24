from flask import jsonify, Flask
import database as db
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://localhost:3000"}})


@app.route('/projects', methods=['GET'])
def get_projects():
    attrs = ['id', 'owner', 'name', 'primaryLanguage']
    projects = db.query(db.Project)
    return jsonify([{a: getattr(p, a) for a in attrs} for p in projects])


if __name__ == '__main__':
    db.connect()
    app.run(debug=True)
