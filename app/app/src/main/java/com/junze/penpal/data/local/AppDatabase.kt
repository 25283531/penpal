package com.junze.penpal.data.local

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

// ---------- Entities (offline cache) ----------

@Entity(tableName = "characters")
data class CharacterEntity(
    @PrimaryKey val id: String,
    val name: String,
    val age: Int?,
    val occupation: String?,
    val appearance: String?,
    val personality: String?,
    val hobbies: String?, // joined with "\n"
    val writingStyle: String?,
    val topics: String?, // joined with "\n"
    val relationship: String?,
    val photoUrl: String?,
    val photoStatus: String?,
    val unlocked: Boolean
)

@Entity(tableName = "letters")
data class LetterEntity(
    @PrimaryKey val id: Int,
    val characterId: String,
    val direction: String,
    val text: String,
    val status: String?,
    val replyDueAt: String?,
    val isFirst: Boolean?,
    val aiGenerated: Boolean?,
    val readAt: String?,
    val createdAt: String?
)

// ---------- DAOs ----------

@Dao
interface CharacterDao {
    @Query("SELECT * FROM characters ORDER BY id ASC")
    fun observeAll(): Flow<List<CharacterEntity>>

    @Query("SELECT * FROM characters WHERE id = :id")
    suspend fun getById(id: String): CharacterEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(characters: List<CharacterEntity>)
}

@Dao
interface LetterDao {
    @Query("SELECT * FROM letters ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<LetterEntity>>

    @Query("SELECT * FROM letters WHERE characterId = :characterId ORDER BY createdAt ASC")
    fun observeByCharacter(characterId: String): Flow<List<LetterEntity>>

    @Query("SELECT * FROM letters WHERE id = :id")
    suspend fun getById(id: Int): LetterEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(letters: List<LetterEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(letter: LetterEntity)
}

// ---------- Database ----------

@Database(entities = [CharacterEntity::class, LetterEntity::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun characterDao(): CharacterDao
    abstract fun letterDao(): LetterDao

    companion object {
        @Volatile
        private var instance: AppDatabase? = null

        fun get(context: Context): AppDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "penpal.db"
                ).build().also { instance = it }
            }
    }
}
