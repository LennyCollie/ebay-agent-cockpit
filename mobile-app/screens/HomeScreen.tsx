import React, { useState, useEffect } from 'react';
import { StyleSheet, ScrollView, RefreshControl, Alert } from 'react-native';
import { View, Text, SafeAreaView } from 'react-native';
import axios from 'axios';
import { useAuthStore } from '../store/auth';
import { API_URL } from '../config';

export default function HomeScreen() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const { token } = useAuthStore();

  useEffect(() => {
    loadAlerts();
  }, []);

  const loadAlerts = async () => {
    if (!token) return;

    try {
      setLoading(true);
      const response = await axios.get(`${API_URL}/api/alerts`, {
        headers: { Authorization: `Bearer ${token}` }
      });

      if (response.data.success) {
        setAlerts(response.data.data.slice(0, 10));
      }
    } catch (error) {
      Alert.alert('Error', 'Failed to load alerts');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadAlerts();
    setRefreshing(false);
  };

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
      >
        <View style={styles.header}>
          <Text style={styles.title}>Meine Artikel</Text>
          <Text style={styles.subtitle}>{alerts.length} aktive Warnungen</Text>
        </View>

        {alerts.length === 0 ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyText}>Noch keine Artikel überwacht</Text>
          </View>
        ) : (
          alerts.map((alert, idx) => (
            <View key={idx} style={styles.alertCard}>
              <Text style={styles.alertTitle} numberOfLines={2}>
                {alert.item_title}
              </Text>
              <View style={styles.priceRow}>
                <Text style={styles.currentPrice}>
                  €{alert.current_price?.toFixed(2) || '0.00'}
                </Text>
                <Text style={styles.targetPrice}>
                  Ziel: €{alert.target_price?.toFixed(2) || '0.00'}
                </Text>
              </View>
              <View style={styles.statusRow}>
                <Text
                  style={[
                    styles.status,
                    alert.is_enabled ? styles.active : styles.inactive
                  ]}
                >
                  {alert.is_enabled ? 'Aktiv' : 'Inaktiv'}
                </Text>
                <Text style={styles.date}>
                  {new Date(alert.created_at).toLocaleDateString('de-DE')}
                </Text>
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f9fafb',
  },
  header: {
    padding: 20,
    backgroundColor: '#ffffff',
    borderBottomWidth: 1,
    borderBottomColor: '#e5e7eb',
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#1f2937',
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 14,
    color: '#6b7280',
  },
  alertCard: {
    backgroundColor: '#ffffff',
    margin: 12,
    padding: 16,
    borderRadius: 12,
    borderLeftWidth: 4,
    borderLeftColor: '#3b82f6',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 2,
    elevation: 2,
  },
  alertTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 8,
  },
  priceRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  currentPrice: {
    fontSize: 18,
    fontWeight: '700',
    color: '#3b82f6',
  },
  targetPrice: {
    fontSize: 14,
    color: '#6b7280',
  },
  statusRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  status: {
    fontSize: 12,
    fontWeight: '600',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  active: {
    backgroundColor: '#d1fae5',
    color: '#065f46',
  },
  inactive: {
    backgroundColor: '#fee2e2',
    color: '#7f1d1d',
  },
  date: {
    fontSize: 12,
    color: '#9ca3af',
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 60,
  },
  emptyText: {
    fontSize: 16,
    color: '#9ca3af',
    textAlign: 'center',
  },
});
