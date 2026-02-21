import React, { useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { useStore } from '../store/useStore';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import { LineChart } from 'lucide-react';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
);

export const TubChart: React.FC = () => {
  const { records } = useStore();

  const data = useMemo(() => {
    if (!records.length) return { labels: [], datasets: [] };

    // Use a subset of records for performance if needed, but charting 10k points might be heavy
    // Let's sample if too many
    const maxPoints = 1000;
    const step = Math.ceil(records.length / maxPoints);
    const sampledRecords = records.filter((_, i) => i % step === 0);

    const labels = sampledRecords.map(r => r._index);
    const angleData = sampledRecords.map(r => r['user/angle']);
    const throttleData = sampledRecords.map(r => r['user/throttle']);

    return {
      labels,
      datasets: [
        {
          label: 'Angle',
          data: angleData,
          borderColor: 'rgb(6, 182, 212)', // Cyan-500
          backgroundColor: 'rgba(6, 182, 212, 0.5)',
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.1
        },
        {
          label: 'Throttle',
          data: throttleData,
          borderColor: 'rgb(234, 179, 8)', // Yellow-500
          backgroundColor: 'rgba(234, 179, 8, 0.5)',
          borderWidth: 1,
          pointRadius: 0,
           tension: 0.1
        },
      ],
    };
  }, [records]);

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top' as const,
        labels: {
            color: '#e4e4e7' // zinc-200
        }
      },
    },
    scales: {
        x: {
            ticks: { color: '#71717a' }, // zinc-500
            grid: { color: '#27272a' } // zinc-800
        },
        y: {
            ticks: { color: '#71717a' },
            grid: { color: '#27272a' }
        }
    },
    animation: {
        duration: 0 // Disable animation for performance
    }
  };

  if (!records.length) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <LineChart className="w-5 h-5" />
          Data Graph
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[300px] w-full">
          <Line options={options} data={data} />
        </div>
      </CardContent>
    </Card>
  );
};
