import React from 'react';
import CssBaseline from '@material-ui/core/CssBaseline';
import {AuthContext, AuthHandler} from "./Auth";
import App from "./App";
import Splash from "./Splash";

export default function Loader() {
    console.log("Rendering loader");

    const [projects, setProjects] = React.useState([])

    const [status, setStatus] = React.useState({});

    const auth = React.useContext(AuthContext);

    // Fetches projects once in the beginning
    React.useEffect(() => {
        if (auth.user !== null) {
            fetch('/api/projects', {headers: {Authorization: `Bearer ${auth.token}`}})
                .then(res => res.json())
                .then(data => {
                    if ('error' in data) {
                        console.error(data.error);
                    } else {
                        setProjects(data);
                    }
                }).catch(err => {
                    console.error(err)
                }
            );
        }
    }, [auth]);

    // Fetches status in the beginning and listen for server side events
    React.useEffect(() => {
        if (auth.user !== null) {
            fetch('/api/status', {headers: {Authorization: `Bearer ${auth.token}`}})
                .then(res => res.json())
                .then(data => {
                    if ('error' in data) {
                        console.error(data.error);
                    } else {
                        setStatus(data);
                        const evtSource = new EventSource('/api/stream', {headers: {Authorization: `Bearer ${auth.token}`}});
                        evtSource.onmessage = (event) => {
                            let data = JSON.parse(event.data);
                            if ('error' in data) {
                                console.error(data.error);
                            } else {
                                setStatus(old_status => {
                                    let new_status = Object.assign({}, old_status);
                                    new_status[data['project_id']][data['label_id']] = {
                                        isValidated: data['isValidated'],
                                        isAccepted: data['isAccepted']
                                    };
                                    return new_status;
                                })
                            }
                        }
                    }
                }).catch(err => {
                    console.error(err)
                }
            );
        }
    }, [auth]);

    return (
        <div>
            <CssBaseline/>
            {(auth.user === null || projects.length === 0 || status.length === 0) ?
                <Splash/>
                :
                <App auth={auth} projects={projects} status={status} setStatus={setStatus}/>
            }
            <AuthHandler/>
        </div>
    );
}