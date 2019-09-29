import React from 'react';
import List from '@material-ui/core/List';
import ListItem from '@material-ui/core/ListItem';
import ListItemText from '@material-ui/core/ListItemText';
import Box from "@material-ui/core/Box";

export default function ProjectsPane(props) {
    console.log("Rendering projects pane");

    const handleClick = (event, index) => {
        if (index !== props.selectedIndex) {
            props.setSelectedIndex(index);
        } else {
            props.setSelectedIndex(null);
        }
    };

    return (
        <Box width="100%" height="100%" overflow="auto">
            <List>
                {props.projects.map((project, index) => (
                    <ListItem key={index}
                              button
                              selected={props.selectedIndex === index}
                              onClick={(event) => handleClick(event, index)}
                    >
                        <ListItemText primary={project.owner + "/" + project.name}
                                      secondary={project.primaryLanguage}
                                      primaryTypographyProps={{'noWrap': true}}/>
                    </ListItem>
                ))}
            </List>
        </Box>
    );
}