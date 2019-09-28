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

export default function ExecutionPanel(props) {
    console.log("Execution panel: " + props.execution);

    const classes = useStyles();

    return (
        <div>
            <Box className={classes.textBox}>
                {props.execution != null ?
                    <div dangerouslySetInnerHTML={{__html: props.execution.output}} align="left"/> : ""}
            </Box>
            <Box className={classes.fabBox}>
                <MuiThemeProvider theme={trafficLightTheme}>
                    <Fab color="primary" className={classes.fab}>
                        <ThumbUpOutlinedIcon/>
                    </Fab>
                    <Fab color="secondary" className={classes.fab}>
                        <ThumbDownOutlinedIcon/>
                    </Fab>
                    <Fab className={classes.fab}>
                        <ClearOutlinedIcon/>
                    </Fab>
                </MuiThemeProvider>
            </Box>
        </div>
    )
}