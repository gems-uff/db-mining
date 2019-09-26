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
import LabelGrid from "./LabelsGrid";
import ProjectsList from "./ProjectsList";
import ExecutionPanel from "./ExecutionPanel";

const drawerWidth = 240;

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
    menuButton: {
        marginRight: theme.spacing(2),
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
        display: 'flex',
        alignItems: 'center',
        padding: theme.spacing(0, 1),
        ...theme.mixins.toolbar,
        justifyContent: 'flex',
    },
    content: {
        flexGrow: 1,
        padding: theme.spacing(3),
        transition: theme.transitions.create('margin', {
            easing: theme.transitions.easing.sharp,
            duration: theme.transitions.duration.leavingScreen,
        }),
        marginLeft: -drawerWidth,
    },
    contentShift: {
        padding: theme.spacing(3),
        transition: theme.transitions.create('margin', {
            easing: theme.transitions.easing.easeOut,
            duration: theme.transitions.duration.enteringScreen,
        }),
        marginLeft: 0,
    }
}));


export default function ProjectsDrawer() {
    const classes = useStyles();

    const [open, setOpen] = React.useState(true);

    const [projects, setProjects] = React.useState([])
    const [project, setProject] = React.useState(null)
    const [labels, setLabels] = React.useState([]);

    React.useEffect(() => {
        fetch('http://localhost:5000/projects')
            .then(res => res.json())
            .then(data => {
                setProjects(data)
                setProject(data[0])
            })
    }, []);

    React.useEffect(() => {
        if (project != null) {
            fetch('http://localhost:5000/projects/' + project.id + '/labels')
                .then(res => res.json())
                .then(data => {
                    setLabels(data);
                });
        }
    }, [project]);

    const handleClick = () => {
        setOpen(!open);
    };

    return (
        <React.Fragment>
            <CssBaseline/>
            <AppBar
                position="fixed"
                className={clsx(classes.appBar, {
                    [classes.appBarShift]: open,
                })}
            >
                <Toolbar>
                    <IconButton
                        color="inherit"
                        onClick={handleClick}
                        edge="start"
                        className={classes.menuButton}
                    >
                        {open ? <ChevronLeftIcon/> : <MenuIcon/>}
                    </IconButton>
                    <Typography variant="h6" noWrap>
                        {(project != null) ? project.owner + "/" + project.name : "Loading..."}
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
                <ProjectsList projects={projects} setProject={setProject}/>
            </Drawer>
            <main
                className={clsx(classes.content, {
                    [classes.contentShift]: open,
                })}
            >
                <div className={classes.drawerHeader}/>
                <LabelGrid labels={labels}/>
                <ExecutionPanel/>
            </main>
        </React.Fragment>
    );
}