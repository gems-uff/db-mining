import React from 'react';
import List from '@material-ui/core/List';
import ListItem from '@material-ui/core/ListItem';
import ListItemText from '@material-ui/core/ListItemText';
import Box from "@material-ui/core/Box";
import Badge from "@material-ui/core/Badge";

export default function ProjectsPane(props) {
    console.log("Rendering projects pane");

    const pending = (index) => {
        let count = 0;
        let dict = props.status[props.projects[index].id];
        if (dict !== undefined) {
            count = Object.values(dict).filter(label => !label['isValidated']).length;
        }
        return count;
    };

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
                        <Badge badgeContent={pending(index)} color="error"/>
                    </ListItem>
                ))}
            </List>
        </Box>
    );
}