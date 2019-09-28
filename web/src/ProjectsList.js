import React from 'react';
import List from '@material-ui/core/List';
import ListItem from '@material-ui/core/ListItem';
import ListItemText from '@material-ui/core/ListItemText';
import Box from "@material-ui/core/Box";

export default function ProjectsList(props) {
    console.log("Rendering project list");

    const [selectedIndex, setSelectedIndex] = React.useState(-1);

    const handleClick = (event, index) => {
        if (index != selectedIndex) {
            setSelectedIndex(index);
            props.setProject(props.projects[index])
        } else {
            setSelectedIndex(-1);
            props.setProject(null);
        }
    };

    return (
        <Box width="100%" height="100%" overflow="auto">
        <List>
            {props.projects.map((project, index) => (
                <ListItem key={index}
                          button
                          selected={selectedIndex === index}
                          onClick={(event) => handleClick(event, index)}
                >
                    <ListItemText primary={project.owner + "/" + project.name}
                                  secondary={project.primaryLanguage}
                                  primaryTypographyProps={{'noWrap':true}}/>
                </ListItem>
            ))}
        </List>
        </Box>
    );
}