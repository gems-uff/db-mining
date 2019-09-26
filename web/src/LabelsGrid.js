import React from "react";
import Chip from "@material-ui/core/Chip";
import Box from "@material-ui/core/Box";
import Grid from "@material-ui/core/Grid";
import Paper from "@material-ui/core/Paper";
import makeStyles from "@material-ui/core/styles/makeStyles";

const height = 150

const useStyles = makeStyles(theme => ({
  paper: {
    display: 'flex',
    flexWrap: 'wrap',
    padding: theme.spacing(2),
    textAlign: 'center',
    color: theme.palette.text.secondary,
  }
}));

export default function LabelGrid(props) {
    // const [selectedLabelIndex, setSelectedLabelIndex] = React.useState(0);

    const classes = useStyles();

    function handleClick() {
        console.log('click')
    }

    return (
        <Paper className={classes.paper}>
            <Box width="100%" height={height} overflow="auto">
                <Grid container spacing={1}>
                    {props.labels.map((label, index) => (
                        <Grid item xs={2} key={index}>
                            <Chip label={label.name} onClick={handleClick}/>
                        </Grid>
                    ))}
                </Grid>
            </Box>
        </Paper>
    )
}