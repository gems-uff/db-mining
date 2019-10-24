import json

from flask import jsonify, render_template, request, Response
from flask_cors import CORS
from sqlalchemy import func
from queue import Queue
import database as db
from auth import login_required

app = db.app
CORS(app)

queues = []


@app.route('/')
def react():
    return render_template('index.html')


@app.route('/implicit/callback')
def callback():
    return render_template('index.html')


@app.route('/api/status', methods=['GET'])
@login_required
def get_status():
    result_set = db.query(db.Version.project_id.label('project_id'),
                          db.Heuristic.label_id.label('label_id'),
                          db.Execution.isValidated.label('isValidated'),
                          db.Execution.isAccepted.label('isAccepted')
                          ) \
        .join(db.Version.executions) \
        .join(db.Execution.heuristic) \
        .filter(db.Execution.output != '').all()

    status = {}
    for row in result_set:
        labels = status.get(row.project_id)
        if not labels:
            labels = {}
            status[row.project_id] = labels
        labels[row.label_id] = {'isValidated': row.isValidated, 'isAccepted': row.isAccepted}

    return jsonify(status)


@app.route('/api/projects', methods=['GET'])
@login_required
def get_projects():
    projects = db.query(db.Project.id.label('id'),
                        db.Project.owner.label('owner'),
                        db.Project.name.label('name'),
                        db.Project.primaryLanguage.label('primaryLanguage'),
                        db.Project.domain.label('domain')
                        ) \
        .order_by(func.lower(db.Project.owner)) \
        .order_by(func.lower(db.Project.name)).all()
    return jsonify([project._asdict() for project in projects])


@app.route('/api/projects/<int:project_id>', methods=['GET'])
@login_required
def get_project(project_id):
    project = db.query(db.Project, id=project_id).first()
    attrs = vars(project).copy()  # All attributes
    del attrs['_sa_instance_state']  # But this internal SQLAlchemy attribute
    return jsonify({a: getattr(project, a) for a in attrs})


def labels_query(project_id):
    return db.query(db.Label.id.label('id'),
                    db.Label.name.label('name'),
                    db.Execution.output.label('output')
                    ) \
        .join(db.Label.heuristic) \
        .join(db.Heuristic.executions) \
        .join(db.Execution.version) \
        .filter(db.Version.project_id == project_id) \
        .filter(db.Execution.output != '') \
        .order_by(func.lower(db.Label.name))


def label2dict(label, project_id):
    result = label._asdict()
    result['project_id'] = project_id
    return result


@app.route('/api/projects/<int:project_id>/labels', methods=['GET'])
@login_required
def get_labels(project_id):
    labels = labels_query(project_id).all()
    return jsonify([label2dict(label, project_id) for label in labels])


@app.route('/api/projects/<int:project_id>/labels/<int:label_id>', methods=['GET'])
@login_required
def get_label(project_id, label_id):
    label = labels_query(project_id).filter(db.Label.id == label_id).first()
    return jsonify(label2dict(label, project_id))


@app.route('/api/projects/<int:project_id>/labels/<int:label_id>', methods=['PUT'])
@login_required
def put_label(project_id, label_id):
    data = request.get_json()

    execution = db.query(db.Execution) \
        .join(db.Execution.version) \
        .join(db.Execution.heuristic) \
        .filter(db.Version.project_id == project_id) \
        .filter(db.Heuristic.label_id == label_id).first()
    execution.isValidated = data['isValidated']
    execution.isAccepted = data['isAccepted']
    db.commit()

    data['project_id'] = project_id
    data['label_id'] = label_id

    data = json.dumps(data)
    for queue in queues:
        queue.put(data)

    return jsonify(success=True)


def event_stream(queue):
    while True:
        data = queue.get()
        yield f'data: {data}\n\n'


@app.route('/api/stream')
def stream():
    queue = Queue()
    queues.append(queue)
    return Response(event_stream(queue), mimetype='text/event-stream', headers={'Cache-Control': 'no-transform'})


if __name__ == '__main__':
    db.connect()
    # app.run(host='0.0.0.0', debug=True)
    app.run(debug=True)
