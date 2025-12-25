import React, { useState, useEffect } from 'react';
import { StyleSheet, ScrollView, RefreshControl } from 'react-native';
import { View, Text, SafeAreaView } from 'react-native';
import axios from 'axios';
import { useAuthStore } from '../store/auth';
import { API_URL, COLORS } from '../config';

export default function AnalyticsScreen() {
  const { token } = useAuthStore();
  const [analytics, setAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    loadAnalytics();
  }, []);

  const loadAnalytics = async () => {
    if (!token) return;

    try {
      setLoading(true);
      const response = await axios.get(`${API_URL}/api/analytics/dashboard`, {
        headers: { Authorization: `Bearer ${token}` }
      });

      if (response.data.success) {
        setAnalytics(response.data.data);
      }
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await loadAnalytics();
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
          <Text style={styles.title}>Analyse & Statistiken</Text>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Übersicht</Text>
          
          <View style={styles.metricsGrid}>
            <View style={styles.metricCard}>
              <Text style={styles.metricValue}>
                {analytics?.total_alerts || 0}
              </Text>
              <Text style={styles.metricLabel}>Insgesamt</Text>
            </View>

            <View style={styles.metricCard}>
              <Text style={styles.metricValue}>
                {analytics?.active_alerts || 0}
              </Text>
              <Text style={styles.metricLabel}>Aktiv</Text>
            </View>

            <View style={styles.metricCard}>
              <Text style={styles.metricValue}>
                €{(analytics?.total_saved || 0).toFixed(2)}
              </Text>
              <Text style={styles.metricLabel}>Gespart</Text>
            </View>

            <View style={styles.metricCard}>
              <Text style={styles.metricValue}>
                {analytics?.price_drops || 0}
              </Text>
              <Text style={styles.metricLabel}>Preisfälle</Text>
            </View>
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Kategorien</Text>
          
          {analytics?.top_categories?.slice(0, 5).map((cat: any, idx: number) => (
            <View key={idx} style={styles.categoryRow}>
              <Text style={styles.categoryName}>{cat.name}</Text>
              <View style={styles.categoryBar}>
                <View
                  style={[
                    styles.categoryBarFill,
                    { width: `${(cat.count / (analytics?.top_categories[0]?.count || 1)) * 100}%` }
                  ]}
                />
              </View>
              <Text style={styles.categoryCount}>{cat.count}</Text>
            </View>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Aktivität</Text>
          
          <View style={styles.activityCard}>
            <View style={styles.activityRow}>
              <Text style={styles.activityLabel}>Heute</Text>
              <Text style={styles.activityValue}>
                {analytics?.today_notifications || 0} Benachrichtigungen
              </Text>
            </View>
            <View style={styles.activityRow}>
              <Text style={styles.activityLabel}>Diese Woche</Text>
              <Text style={styles.activityValue}>
                {analytics?.week_notifications || 0} Benachrichtigungen
              </Text>
            </View>
            <View style={styles.activityRow}>
              <Text style={styles.activityLabel}>Dieser Monat</Text>
              <Text style={styles.activityValue}>
                {analytics?.month_notifications || 0} Benachrichtigungen
              </Text>
            </View>
          </View>
        </View>
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
    backgroundColor: COLORS.surface,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: COLORS.text,
  },
  section: {
    marginTop: 20,
    paddingHorizontal: 16,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: COLORS.textSecondary,
    marginBottom: 12,
    textTransform: 'uppercase',
  },
  metricsGrid: {
    display: 'flex',
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  metricCard: {
    flex: 1,
    minWidth: '45%',
    backgroundColor: COLORS.surface,
    padding: 16,
    borderRadius: 12,
    borderLeftWidth: 4,
    borderLeftColor: COLORS.primary,
  },
  metricValue: {
    fontSize: 24,
    fontWeight: '700',
    color: COLORS.primary,
  },
  metricLabel: {
    fontSize: 12,
    color: COLORS.textSecondary,
    marginTop: 4,
  },
  categoryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
    backgroundColor: COLORS.surface,
    padding: 12,
    borderRadius: 8,
  },
  categoryName: {
    fontSize: 14,
    fontWeight: '600',
    color: COLORS.text,
    width: 100,
  },
  categoryBar: {
    flex: 1,
    height: 20,
    backgroundColor: COLORS.border,
    borderRadius: 4,
    marginHorizontal: 8,
    overflow: 'hidden',
  },
  categoryBarFill: {
    height: '100%',
    backgroundColor: COLORS.primary,
  },
  categoryCount: {
    fontSize: 12,
    fontWeight: '600',
    color: COLORS.text,
    width: 30,
    textAlign: 'right',
  },
  activityCard: {
    backgroundColor: COLORS.surface,
    padding: 16,
    borderRadius: 12,
  },
  activityRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.border,
  },
  activityLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: COLORS.text,
  },
  activityValue: {
    fontSize: 14,
    fontWeight: '600',
    color: COLORS.primary,
  },
});
