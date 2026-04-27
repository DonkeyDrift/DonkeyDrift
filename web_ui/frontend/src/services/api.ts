import axios from 'axios';

const API_URL = 'http://localhost:8000/api';

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const loadConfig = async (path: string) => {
  const response = await api.post('/config/load', { path });
  return response.data;
};

export const selectDirectory = async () => {
  const response = await api.get('/config/select_directory');
  return response.data;
};

export const loadTub = async (path: string) => {
  const response = await api.post('/tub/load', { path });
  return response.data;
};

export const getRecords = async (offset = 0, limit = 100) => {
  const response = await api.get('/tub/records', { params: { offset, limit } });
  return response.data;
};

export const deleteRecords = async (indexes: number[]) => {
  const response = await api.post('/tub/delete', { indexes });
  return response.data;
};

export const restoreRecords = async (indexes: number[]) => {
  const response = await api.post('/tub/restore', { indexes });
  return response.data;
};

export const getImageUrl = (path: string) => {
  return `${API_URL}/tub/image?path=${encodeURIComponent(path)}`;
};
