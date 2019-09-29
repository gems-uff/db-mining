import React from "react";
import Box from "@material-ui/core/Box";
import ToggleButton from "@material-ui/lab/ToggleButton";
import ToggleButtonGroup from "@material-ui/lab/ToggleButtonGroup";
import {makeStyles} from "@material-ui/core";

const useStyles = makeStyles(theme => ({
    buttonBox: {
        position: 'fixed',
        width: 'inherit',
        padding: theme.spacing(1),
        overflow: 'auto'
    }
}));

export default function LabelsPane(props) {
    console.log("Rendering labels pane");

    const classes = useStyles();

    function handleClick(event, index) {
        props.setSelectedIndex(index);
    }

    return (
        <Box className={classes.buttonBox}>
            <ToggleButtonGroup exclusive onChange={handleClick} value={props.selectedIndex}>
                {props.labels.map((label, index) => (
                    <ToggleButton key={index} value={index}>
                        {label.name}
                    </ToggleButton>
                ))}
            </ToggleButtonGroup>
        </Box>
    )
}