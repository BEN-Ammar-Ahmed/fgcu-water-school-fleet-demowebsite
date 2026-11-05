-- Run once while connected to the 'master' database (or any database), then
-- reconnect / switch to WSB_Vehicle_Database before running 01_schema.sql.
IF DB_ID('WSB_Vehicle_Database') IS NULL
    CREATE DATABASE WSB_Vehicle_Database;
GO
