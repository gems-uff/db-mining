import React from "react";
import Box from "@material-ui/core/Box";
import ToggleButton from "@material-ui/lab/ToggleButton";
import ToggleButtonGroup from "@material-ui/lab/ToggleButtonGroup";
import {makeStyles, MuiThemeProvider} from "@material-ui/core";
import createMuiTheme from "@material-ui/core/styles/createMuiTheme";
import Fab from "@material-ui/core/Fab";
import ThumbUpOutlinedIcon from '@material-ui/icons/ThumbUpOutlined';
import ThumbDownOutlinedIcon from '@material-ui/icons/ThumbDownOutlined';
import ClearOutlinedIcon from '@material-ui/icons/ClearOutlined';
import Ansi from "ansi-to-react";
import Tooltip from "@material-ui/core/Tooltip";
import Typography from "@material-ui/core/Typography";

const useStyles = makeStyles(theme => ({
    span: {
        whiteSpace: 'nowrap',
        verticalAlign: 'middle',
        display: 'inline-flex'
    },
    buttonBox: {
        position: 'fixed',
        width: 'inherit',
        padding: theme.spacing(1),
        overflow: 'auto'
    },
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
    },
    rightIcon: {
        marginLeft: theme.spacing(1)
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

export default function LabelsPane(props) {
    const classes = useStyles();

    function handleToggle(event, index) {
        props.setSelectedIndex(index);
        window.scrollTo(0, 0)
    }

    const auth = props.auth;

    function handleFab(isValidated, isAccepted) {
        let init = {
            headers: {
                "Content-Type": "application/json; charset=utf-8",
                Authorization: `Bearer ${auth.token}`
            },
            method: 'PUT',
            body: JSON.stringify({
                isValidated: isValidated,
                isAccepted: isAccepted
            })
        };
        fetch('/api/projects/' + props.labels[props.selectedIndex].project_id + '/labels/' + props.labels[props.selectedIndex].id, init)
            .catch(err => {
                    console.error(err);
                }
            );
    }

    return (
        <MuiThemeProvider theme={trafficLightTheme}>
            <Box className={classes.buttonBox}>
                <ToggleButtonGroup exclusive onChange={handleToggle} value={props.selectedIndex}>
                    {props.labels.map((label, index) => (
                        <ToggleButton key={index} value={index}>
                            <Tooltip title={
                                <React.Fragment>
                                    <Typography>Type: {label.type}</Typography>
                                    {props.status[label.project_id][label.id]['user'] !== null &&
                                        <Typography>Validated by {props.status[label.project_id][label.id]['user']}</Typography>
                                    }
                                </React.Fragment>
                            } placement={"bottom"}>
                                <span className={classes.span}>
                                    {label.name}
                                    {props.status[label.project_id][label.id]['isValidated'] &&
                                    (props.status[label.project_id][label.id]['isAccepted'] ?
                                        <ThumbUpOutlinedIcon className={classes.rightIcon} color='primary'/> :
                                        <ThumbDownOutlinedIcon className={classes.rightIcon} color='secondary'/>)
                                    }
                                </span>
                            </Tooltip>
                        </ToggleButton>
                    ))}
                </ToggleButtonGroup>
            </Box>
            {props.selectedIndex !== null &&
            <React.Fragment>
                <Box className={classes.textBox}>
                    {props.labels[props.selectedIndex].output.split('\n').map((line, key) => {
                        if (line !== '' && (line.charAt(0) < '0' || line.charAt(0) > '9')) {
                            if (line.charCodeAt(0) !== 27) {
                                return <React.Fragment key={key}><h3>{line}</h3><br/></React.Fragment>
                            } else {
                                return <React.Fragment key={key}><br/><hr/><br/></React.Fragment>
                            }
                        } else {
                            return <React.Fragment key={key}><Ansi linkify={false}>{line}</Ansi><br/></React.Fragment>
                        }
                    })}
                </Box>
                <Box className={classes.fabBox}>
                    <Fab color="primary" className={classes.fab} onClick={() => handleFab(true, true)}>
                        <ThumbUpOutlinedIcon/>
                    </Fab>
                    <Fab color="secondary" className={classes.fab} onClick={() => handleFab(true, false)}>
                        <ThumbDownOutlinedIcon/>
                    </Fab>
                    <Fab className={classes.fab} onClick={() => handleFab(false, false)}>
                        <ClearOutlinedIcon/>
                    </Fab>
                </Box>
            </React.Fragment>
            }
        </MuiThemeProvider>
    )
}