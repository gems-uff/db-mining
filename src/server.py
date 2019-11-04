import os
import sys

sys.path.append(os.path.dirname(__file__))

from util import REACT_BUILD_DIR
from threading import Timer
import json
from flask import jsonify, request, Response, g, send_from_directory
from flask_cors import CORS
from sqlalchemy import func
from queue import Queue
import database as db
from auth import login_required

application = db.application
CORS(application)

queues = []  # TODO: check if it is possible to just eliminate the unused queues (number of pending messages?)
PING_DELAY = 50  # To avoid timeout after 60 seconds of inactivity
RESET_DELAY = 24 * 60 * 60  # To clean the resources every day


# Serve React App
@application.route('/', defaults={'path': ''})
@application.route('/<path:path>')
def react(path):
    if path and os.path.exists(REACT_BUILD_DIR + os.sep + path):
        return send_from_directory(REACT_BUILD_DIR, path)
    else:
        return send_from_directory(REACT_BUILD_DIR, 'index.html')


@application.route('/api/status', methods=['GET'])
@login_required
def get_status():
    result_set = db.query(db.Version.project_id.label('project_id'),
                          db.Heuristic.label_id.label('label_id'),
                          db.Execution.isValidated.label('isValidated'),
                          db.Execution.isAccepted.label('isAccepted'),
                          db.Execution.user.label('user')
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
        labels[row.label_id] = {
            'isValidated': row.isValidated,
            'isAccepted': row.isAccepted,
            'user': row.user
        }

    return jsonify(status)


@application.route('/api/projects', methods=['GET'])
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


def labels_query(project_id):
    return db.query(db.Label.id.label('id'),
                    db.Label.name.label('name'),
                    db.Label.type.label('type'),
                    db.Execution.output.label('output')
                    ) \
        .join(db.Label.heuristic) \
        .join(db.Heuristic.executions) \
        .join(db.Execution.version) \
        .filter(db.Version.project_id == project_id) \
        .filter(db.Execution.output != '') \
        .order_by(func.lower(db.Label.type)) \
        .order_by(func.lower(db.Label.name))


def label2dict(label, project_id):
    result = label._asdict()
    result['project_id'] = project_id
    return result


@application.route('/api/projects/<int:project_id>/labels', methods=['GET'])
@login_required
def get_labels(project_id):
    labels = labels_query(project_id).all()
    return jsonify([label2dict(label, project_id) for label in labels])


@application.route('/api/projects/<int:project_id>/labels/<int:label_id>', methods=['PUT'])
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
    execution.user = g.user
    db.commit()

    data['project_id'] = project_id
    data['label_id'] = label_id
    data['user'] = g.user
    publish(json.dumps(data))

    return jsonify(success=True)


def ping():
    publish(json.dumps('ping'))
    Timer(PING_DELAY, ping).start()


def reset():
    publish(None)
    queues.clear()
    Timer(RESET_DELAY, reset).start()


def publish(data):
    for queue in queues:
        queue.put(data)


def listen(queue):
    while True:
        data = queue.get()
        if not data:
            break
        yield f'data: {data}\n\n'


@application.route('/api/stream')
def stream():
    queue = Queue()
    queues.append(queue)
    return Response(listen(queue), mimetype='text/event-stream', headers={'Cache-Control': 'no-transform'})


db.connect()
Timer(PING_DELAY, ping).start()
Timer(RESET_DELAY, reset).start()

if __name__ == '__main__':
    application.run(debug=True)
