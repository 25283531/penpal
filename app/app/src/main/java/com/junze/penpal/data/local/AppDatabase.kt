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
    val gender: String?,
    val occupation: String?,
    val appearance: String?,
    val personality: String?,
    val hobbies: String?, // joined with "\n"
    val writingStyle: String?,
    val topics: String?, // joined with "\n"
    val relationship: String?,
    val photoUrl: String?,
    val photoStatus: String?,
    val motto: String?,
    val city: String?,
    /** photo urls joined with "\n" (null urls are dropped; UI pads to 3 slots). */
    val photos: String?,
    /** candid photo urls joined with "\n"; cached for future reply attachments, not shown yet. */
    val candidPhotos: String?,
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
    val createdAt: String?,
    val userReadAt: String?,
    val characterReadAt: String?,
    val expectedReplyAt: String?,
    val deliveryStage: String?,
    val deliveryStageText: String?
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

// v3 adds character candidPhotos (cached for future reply attachments).
// v2 adds character gender/motto/city/photos and letter
// user_read_at / character_read_at / expected_reply_at /
// delivery_stage(_text). Pre-release app: destructive migration is fine
// (the cache is rebuilt from the server on next refresh).
@Database(entities = [CharacterEntity::class, LetterEntity::class], version = 3, exportSchema = false)
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
                ).fallbackToDestructiveMigration().build().also { instance = it }
            }
    }
}
