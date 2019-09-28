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

export default function LabelGrid(props) {
    console.log("Rendering labels: " + props.labels);

    const classes = useStyles();

    // TODO: this code should be global, in place of label.
    const [selectedIndex, setSelectedIndex] = React.useState(-1);

    function handleClick(event, index) {
        console.log("click no label: " + index);
        setSelectedIndex(index);
        props.setLabel(props.labels[index]);
    }

    return (
        <Box className={classes.buttonBox}>
            <ToggleButtonGroup exclusive onChange={handleClick} value={selectedIndex}>
                {props.labels.map((label, index) => (
                    <ToggleButton key={index} value={index}>
                        {label.name}
                    </ToggleButton>
                ))}
            </ToggleButtonGroup>
        </Box>
    )
}