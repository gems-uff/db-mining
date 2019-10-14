import * as React from 'react';
import {withRouter} from 'react-router-dom';
import {withAuth} from '@okta/okta-react';

export const AuthContext = React.createContext();

const getUserFromToken = token => {
    if (token) {
        try {
            return JSON.parse(atob(token.split('.')[1]));
        } catch (error) {
            // ignore
        }
    }

    return null;
};

export const AuthProvider = ({children}) => {
    const [state, setState] = React.useReducer((oldState, newState) => newState, {
        loading: true,
        token: undefined,
        user: null,
    });

    const updateAuth = async auth => {
        const token = (await auth.getIdToken()) || null;
        if (token !== state.token) {
            setState({
                token,
                loading: false,
                user: getUserFromToken(token),
            });
        }
    };

    return (
        <AuthContext.Provider value={{...state, updateAuth}}>
            {children}
        </AuthContext.Provider>
    );
};

export const AuthHandler = withAuth(
    withRouter(({auth, location}) => {
        const {updateAuth} = React.useContext(AuthContext);

        React.useEffect(() => {
            updateAuth(auth);
        });

        React.useEffect(() => {
            if (location.pathname === '/login') auth.login('/');
            if (location.pathname === '/logout') auth.logout('/');
        }, [auth, location.pathname]);

        return null;
    }),
);