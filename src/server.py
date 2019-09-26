from flask import jsonify, render_template
from flask_cors import CORS

import database as db

app = db.app
# CORS(app, resources={r"/*": {"origins": "http://localhost:3000"}})
CORS(app, resources={r"/*": {"origins": "*"}})


@app.route('/')
def react():
    return render_template('index.html')


@app.route('/projects', methods=['GET'])
def get_projects():
    projects = db.query(db.Project)
    attrs = ['id', 'owner', 'name', 'primaryLanguage']
    return jsonify([{a: getattr(p, a) for a in attrs} for p in projects])


@app.route('/projects/<int:project_id>', methods=['GET'])
def get_project(project_id):
    project = db.query(db.Project, id=project_id).first()
    attrs = vars(project).copy()  # All attributes
    del attrs['_sa_instance_state']  # But this internal SQLAlchemy attribute
    return jsonify({a: getattr(project, a) for a in attrs})


@app.route('/projects/<int:project_id>/labels', methods=['GET'])
def get_labels(project_id):
    version = db.query(db.Version, project_id=project_id, isLast=True).first()
    executions = version.executions
    labels = [e.heuristic.label for e in executions if e.output]
    attrs = ['id', 'name', 'type']
    return jsonify([{a: getattr(l, a) for a in attrs} for l in labels])


@app.route('/projects/<int:project_id>/labels/<int:label_id>/execution', methods=['GET'])
def get_execution(project_id, label_id):
    execution = db.query(db.Execution)\
        .join(db.Execution.version) \
        .join(db.Execution.heuristic) \
        .filter(db.Version.project_id == project_id) \
        .filter(db.Heuristic.label_id == label_id).first()
    attrs = ['isValidated', 'isAccepted']
    return jsonify({a: getattr(execution, a) for a in attrs})


if __name__ == '__main__':
    db.connect()
    app.run(debug=True)
