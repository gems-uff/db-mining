import Box from "@material-ui/core/Box";
import React from "react";
import Fab from "@material-ui/core/Fab";
import ThumbUpOutlinedIcon from '@material-ui/icons/ThumbUpOutlined';
import ThumbDownOutlinedIcon from '@material-ui/icons/ThumbDownOutlined';
import ClearOutlinedIcon from '@material-ui/icons/ClearOutlined';
import {makeStyles, MuiThemeProvider} from "@material-ui/core";
import createMuiTheme from "@material-ui/core/styles/createMuiTheme";

const useStyles = makeStyles(theme => ({
    textBox: {
        width: '100%',
        height: '100%',
        padding: theme.spacing(1),
        marginTop: 60,
        overflow: 'auto'
    },
    fabBox: {
        position: 'fixed',
        bottom: 20,
        right: 20
    },
    fab: {
        margin: theme.spacing(1),
    }
}));

const trafficLightTheme = createMuiTheme({
    palette: {
        primary: {
            main: '#1b5e20',
        },
        secondary: {
            main: '#b71c1c',
        }
    }
});

export default function ExecutionPane(props) {
    console.log("Rendering execution pane: " + props.execution);

    const classes = useStyles();

    function updateExecution(isValidated, isAccepted) {
        let init = {
            headers: { "Content-Type": "application/json; charset=utf-8" },
            method: 'PUT',
            body: JSON.stringify({
                isValidated: isValidated,
                isAccepted: isAccepted
            })
        };
        fetch('http://localhost:5000/projects/' + props.execution.project_id + '/labels/' + props.execution.label_id + '/execution', init)
            .then(res => res.json())
            .then(json => {
                console.log('TODO: update UI');
            }).catch(err => {
                console.error(err);
            }
        );
    }

    function handleAcceptClick() {
        updateExecution(true, true);
    }

    function handleRejectClick() {
        updateExecution(true, false);
    }

    function handleDiscardClick() {
        updateExecution(false, false);
    }

    return (
        <div>
            <Box className={classes.textBox}>
                <div dangerouslySetInnerHTML={{__html: props.execution.output}} align="left"/>
            </Box>

            <Box className={classes.fabBox}>
                <MuiThemeProvider theme={trafficLightTheme}>
                    <Fab color="primary" className={classes.fab} onClick={handleAcceptClick}>
                        <ThumbUpOutlinedIcon/>
                    </Fab>
                    <Fab color="secondary" className={classes.fab} onClick={handleRejectClick}>
                        <ThumbDownOutlinedIcon/>
                    </Fab>
                    <Fab className={classes.fab} onClick={handleDiscardClick}>
                        <ClearOutlinedIcon/>
                    </Fab>
                </MuiThemeProvider>
            </Box>
        </div>
    )
}