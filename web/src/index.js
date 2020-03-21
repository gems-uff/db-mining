import './index.css';
import React from 'react';
import ReactDOM from 'react-dom';
import {BrowserRouter as Router, Route, Switch} from 'react-router-dom'
import {ImplicitCallback, Security, SecureRoute} from '@okta/okta-react';
import {AuthProvider} from './Auth';
import Loader from "./Loader";
import * as serviceWorker from './serviceWorker';

import authOkta from './authentication.json';

ReactDOM.render((
    <AuthProvider>
        <Router>
            <Security
                issuer={authOkta.issuer}
                client_id={authOkta.client_id}
                redirect_uri={`${window.location.origin}/implicit/callback`}
            >
                <Switch>
                    <Route path="/implicit/callback" component={ImplicitCallback}/>
                    <SecureRoute path="/" component={Loader}/>
                </Switch>
            </Security>
        </Router>
    </AuthProvider>
), document.getElementById('root'));

// If you want your app to work offline and load faster, you can change
// unregister() to register() below. Note this comes with some pitfalls.
// Learn more about service workers: https://bit.ly/CRA-PWA
serviceWorker.unregister();
