import { useState } from 'react';
import {
    Box,
    TextField,
    Button,
    Typography,
    List,
    ListItem,
    ListItemText,
    Paper,
} from '@mui/material';
import axios from 'axios';

const endpointMapping = {
    'Notion': 'notion',
    'Airtable': 'airtable',
    'HubSpot': 'hubspot/get_hubspot_items',
};

export const DataForm = ({ integrationType, credentials }) => {
    const [loadedData, setLoadedData] = useState(null);
    const [loading, setLoading] = useState(false);
    const endpoint = endpointMapping[integrationType];

    const handleLoad = async () => {
        try {
            setLoading(true);
            const formData = new FormData();
            formData.append('credentials', JSON.stringify(credentials));
            const response = await axios.post(`http://localhost:8000/integrations/${endpoint}`, formData);
            const data = response.data;
            setLoadedData(data);
        } catch (e) {
            alert(e?.response?.data?.detail);
        } finally {
            setLoading(false);
        }
    }

    const renderData = () => {
        if (!loadedData) return null;

        return (
            <Paper elevation={3} sx={{ mt: 2, p: 2, maxHeight: 400, overflow: 'auto', width: '100%' }}>
                <List>
                    {loadedData.map((item, index) => (
                        <ListItem key={index} divider>
                            <ListItemText
                                primary={item.name}
                                secondary={
                                    <>
                                        <Typography variant="body2">Type: {item.type}</Typography>
                                        <Typography variant="body2">Created: {new Date(item.creation_time).toLocaleString()}</Typography>
                                        <Typography variant="body2">Modified: {new Date(item.last_modified_time).toLocaleString()}</Typography>
                                        {item.url && (
                                            <Typography variant="body2">
                                                <a href={item.url} target="_blank" rel="noopener noreferrer">View in {integrationType}</a>
                                            </Typography>
                                        )}
                                    </>
                                }
                            />
                        </ListItem>
                    ))}
                </List>
            </Paper>
        );
    }

    return (
        <Box display='flex' justifyContent='center' alignItems='center' flexDirection='column' width='100%'>
            <Box display='flex' flexDirection='column' width='100%' maxWidth={600}>
                <Button
                    onClick={handleLoad}
                    sx={{mt: 2}}
                    variant='contained'
                    disabled={loading}
                >
                    {loading ? 'Loading...' : 'Load Data'}
                </Button>
                {loadedData && (
                    <Button
                        onClick={() => setLoadedData(null)}
                        sx={{mt: 1}}
                        variant='outlined'
                        color="secondary"
                    >
                        Clear Data
                    </Button>
                )}
                {renderData()}
            </Box>
        </Box>
    );
}
