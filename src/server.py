from flask import jsonify, Flask, render_template
import database as db
from flask_cors import CORS

from util import REACT_STATIC_DIR, REACT_BUILD_DIR

app = Flask(__name__, static_folder=REACT_STATIC_DIR, template_folder=REACT_BUILD_DIR)
# CORS(app, resources={r"/*": {"origins": "http://localhost:3000"}})
CORS(app, resources={r"/*": {"origins": "*"}})


@app.route("/")
def hello():
    return render_template('index.html')


@app.route('/projects', methods=['GET'])
def get_projects():
    attrs = ['id', 'owner', 'name', 'primaryLanguage']
    projects = db.query(db.Project)
    return jsonify([{a: getattr(p, a) for a in attrs} for p in projects])


if __name__ == '__main__':
    db.connect()
    app.run(debug=True)
