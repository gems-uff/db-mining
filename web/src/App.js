import React from 'react';
import clsx from 'clsx';
import {makeStyles} from '@material-ui/core/styles';
import Drawer from '@material-ui/core/Drawer';
import CssBaseline from '@material-ui/core/CssBaseline';
import AppBar from '@material-ui/core/AppBar';
import Toolbar from '@material-ui/core/Toolbar';
import Typography from '@material-ui/core/Typography';
import Divider from '@material-ui/core/Divider';
import IconButton from '@material-ui/core/IconButton';
import MenuIcon from '@material-ui/icons/Menu';
import ChevronLeftIcon from '@material-ui/icons/ChevronLeft';
import LabelsPane from "./LabelsPane";
import ProjectsPane from "./ProjectsPane";
import ExecutionPane from "./ExecutionPane";

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
    taskBarEntry: {
        marginRight: theme.spacing(1),
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

export default function App() {
    console.log("Rendering drawer");

    const classes = useStyles();

    const [open, setOpen] = React.useState(true);

    const [projects, setProjects] = React.useState([])
    const [selectedProjectIndex, setSelectedProjectIndex] = React.useState(null);

    const [labels, setLabels] = React.useState([]);
    const [selectedLabelIndex, setSelectedLabelIndex] = React.useState(null);

    const [execution, setExecution] = React.useState(null);

    // Fetches projects once in the beginning
    React.useEffect(() => {
        fetch('http://localhost:5000/projects')
            .then(res => res.json())
            .then(data => {
                setProjects(data);
            }).catch(err => {
                console.error(err)
            }
        );
    }, []);

    // Updates labels when selected project changes
    React.useEffect(() => {
        if (selectedProjectIndex !== null) {
            fetch('http://localhost:5000/projects/' + projects[selectedProjectIndex].id + '/labels')
                .then(res => res.json())
                .then(data => {
                    setLabels(data);
                }).catch(err => {
                    console.error(err)
                }
            );
        } else {
            setLabels([]);
        }
        setSelectedLabelIndex(null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedProjectIndex]);

    // Updates execution when the selected label changes
    React.useEffect(() => {
        if (selectedProjectIndex !== null && selectedLabelIndex !== null) {
            fetch('http://localhost:5000/projects/' + projects[selectedProjectIndex].id + '/labels/' + labels[selectedLabelIndex].id + '/execution')
                .then(res => res.json())
                .then(data => {
                    setExecution(data);
                }).catch(err => {
                    console.error(err)
                }
            );
        } else {
            setExecution(null);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedLabelIndex]);

    const handleClick = () => {
        setOpen(!open);
    };

    return (
        <div className={classes.root}>
            <CssBaseline/>
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
                        className={classes.taskBarEntry}
                    >
                        {open ? <ChevronLeftIcon/> : <MenuIcon/>}
                    </IconButton>
                    <Typography variant="h6" noWrap className={classes.taskBarEntry}>
                        {(selectedProjectIndex !== null) ? projects[selectedProjectIndex].owner + "/" + projects[selectedProjectIndex].name : "No project selected"}
                    </Typography>
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
                {projects.length !== 0 && <ProjectsPane projects={projects} selectedIndex={selectedProjectIndex}
                                                        setSelectedIndex={setSelectedProjectIndex}/>}
            </Drawer>
            <main
                className={clsx(classes.content, {
                    [classes.contentShift]: open,
                })}
            >
                <div className={classes.drawerHeader}/>
                {labels.length !== 0 && <LabelsPane labels={labels} selectedIndex={selectedLabelIndex}
                                                    setSelectedIndex={setSelectedLabelIndex}/>}
                {execution !== null && <ExecutionPane execution={execution}/>}
            </main>
        </div>
    );
}