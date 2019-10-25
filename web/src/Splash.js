import {Typography} from "@material-ui/core";
import React from "react";
import CircularProgress from "@material-ui/core/CircularProgress";
import Grid from "@material-ui/core/Grid";

export default function Splash() {
    return (
        <Grid
            container
            spacing={0}
            direction="column"
            alignItems="center"
            justify="center"
            style={{minHeight: '100vh'}}
        >
            <Typography variant={"h4"}>Loading DB-Mining app...</Typography>
            <br/>
            <CircularProgress/>
        </Grid>
    )
}
