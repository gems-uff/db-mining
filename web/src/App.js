import React from 'react';
import clsx from 'clsx';
import {makeStyles} from '@material-ui/core/styles';
import Drawer from '@material-ui/core/Drawer';
import AppBar from '@material-ui/core/AppBar';
import Toolbar from '@material-ui/core/Toolbar';
import Typography from '@material-ui/core/Typography';
import Divider from '@material-ui/core/Divider';
import IconButton from '@material-ui/core/IconButton';
import MenuIcon from '@material-ui/icons/Menu';
import ChevronLeftIcon from '@material-ui/icons/ChevronLeft';
import ExitToAppIcon from '@material-ui/icons/ExitToApp';
import LabelsPane from "./LabelsPane";
import ProjectsPane from "./ProjectsPane";

const drawerWidth = 260;

const useStyles = makeStyles(theme => ({
    root: {
        display: 'flex',
    },
    appBar: {
        transition: theme.transitions.create(['margin', 'width'], {
            easing: theme.transitions.easing.sharp,
            duration: theme.transitions.duration.leavingScreen,
        }),
    },
    appBarShift: {
        width: `calc(100% - ${drawerWidth}px)`,
        marginLeft: drawerWidth,
        transition: theme.transitions.create(['margin', 'width'], {
            easing: theme.transitions.easing.easeOut,
            duration: theme.transitions.duration.enteringScreen,
        }),
    },
    taskBarDrawerButton: {
        color: 'white'
    },
    taskBarTitle: {
        marginLeft: theme.spacing(1),
        color: 'white',
        flexGrow: 1
    },
    taskBarLogoutButton: {
        marginLeft: theme.spacing(1),
        color: 'white'
    },
    hide: {
        display: 'none',
    },
    drawer: {
        width: drawerWidth,
        flexShrink: 0,
    },
    drawerPaper: {
        width: drawerWidth,
    },
    drawerHeader: {
        width: drawerWidth,
        display: 'flex',
        alignItems: 'center',
        ...theme.mixins.toolbar,
        justifyContent: 'flex',
        marginLeft: theme.spacing(1)
    },
    content: {
        width: '100%',
        flexGrow: 1,
        transition: theme.transitions.create(['margin', 'width'], {
            easing: theme.transitions.easing.sharp,
            duration: theme.transitions.duration.leavingScreen,
        }),
        marginLeft: -drawerWidth,
    },
    contentShift: {
        width: `calc(100% - ${drawerWidth}px)`,
        transition: theme.transitions.create(['margin', 'width'], {
            easing: theme.transitions.easing.easeOut,
            duration: theme.transitions.duration.enteringScreen,
        }),
        marginLeft: 0,
    }
}));

export default function App(props) {
    console.log("Rendering drawer");

    const classes = useStyles();

    const [open, setOpen] = React.useState(true);

    const projects = props.projects;
    const [selectedProjectIndex, setSelectedProjectIndex] = React.useState(null);

    const [labels, setLabels] = React.useState([]);
    const [selectedLabelIndex, setSelectedLabelIndex] = React.useState(null);

    const status = props.status;
    const setStatus = props.setStatus;

    const auth = props.auth;

    // Updates labels when selected project changes
    React.useEffect(() => {
        if (selectedProjectIndex !== null) {
            fetch('/api/projects/' + projects[selectedProjectIndex].id + '/labels', {headers: {Authorization: `Bearer ${auth.token}`}})
                .then(res => res.json())
                .then(data => {
                    if ('error' in data) {
                        console.error(data.error);
                    } else {
                        setLabels(data);
                    }
                }).catch(err => {
                    console.error(err)
                }
            );
        } else {
            setLabels([]);
        }
        setSelectedLabelIndex(null);
    }, [projects, selectedProjectIndex, auth]);

    const handleClick = () => {
        setOpen(!open);
    };

    return (
        <div className={classes.root}>
            <AppBar
                position="fixed"
                className={clsx(classes.appBar, {
                    [classes.appBarShift]: open,
                })}
            >
                <Toolbar>
                    <IconButton
                        onClick={handleClick}
                        edge="start"
                        className={classes.taskBarDrawerButton}
                    >
                        {open ? <ChevronLeftIcon/> : <MenuIcon/>}
                    </IconButton>
                    <Typography variant="h6" noWrap className={classes.taskBarTitle}>
                        {(selectedProjectIndex !== null) ? projects[selectedProjectIndex].owner + "/" + projects[selectedProjectIndex].name : "No project selected"}
                    </Typography>
                    <Typography>{auth.user.name}</Typography>
                    <a href={"/logout"}><ExitToAppIcon className={classes.taskBarLogoutButton}/></a>
                </Toolbar>
            </AppBar>
            <Drawer
                className={classes.drawer}
                variant="persistent"
                anchor="left"
                open={open}
                classes={{
                    paper: classes.drawerPaper,
                }}
            >
                <div className={classes.drawerHeader}>
                    <Typography variant="h6">Projects</Typography>
                </div>
                <Divider/>
                {projects.length !== 0 && status.length !== 0 &&
                <ProjectsPane projects={projects}
                              status={status}
                              selectedIndex={selectedProjectIndex}
                              setSelectedIndex={setSelectedProjectIndex}
                />
                }
            </Drawer>
            <main
                className={clsx(classes.content, {
                    [classes.contentShift]: open,
                })}
            >
                <div className={classes.drawerHeader}/>
                {selectedProjectIndex !== null && labels.length !== 0 &&
                <LabelsPane labels={labels}
                            status={status}
                            auth={auth}
                            setStatus={setStatus}
                            selectedIndex={selectedLabelIndex}
                            setSelectedIndex={setSelectedLabelIndex}
                />
                }
            </main>
        </div>
    );
}